"""HA sensor watcher: bridges real HA state-change events to the pure coordinator.

``HASensorWatcher`` subscribes to HA state-changed events for the configured
power and (optionally) temperature entities, drives ``CyclestewardCoordinator.tick()``
on each power update and on a keepalive timer, and dispatches relay actions by
calling HA services on the configured plug entity.

A live power trace ``(timestamp, power_w)`` is accumulated during each session.
The buffer is cleared when a new session starts (CHARGING state entry) and
retained through DONE_LATCHED_OFF so slice 3 can read it for calibration.

Scheduling probe (ADR-0012 B–D): when a ``target_finish_time`` is set and the
coordinator is in WAITING_FOR_SCHEDULE, the watcher computes ``probe_time`` from
the profile's estimated max duration, the configured margin, and a fixed
probe_headroom.  At ``probe_time`` it transitions to PROBING via
``coordinator.start_probe()``, fires a logbook event, and monitors ticks for a
usable SoC reading.  On success or timeout it calls ``coordinator.end_probe()``,
fires a ``probe_result`` logbook event, and updates ``_computed_start_time`` for
subsequent ticks.

All HA imports are deferred to ``async_start()`` call time so the module can
be imported in tests without a real HA runtime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from cyclesteward.session_control import ChargeMode, SessionAction, SessionState

from .const import DEFAULT_MARGIN_S as _DEFAULT_MARGIN_S
from .coordinator import CyclestewardCoordinator

# ADR-0012 C fixed probe headroom (margin default lives in const.py).
_PROBE_HEADROOM_S = 600.0    # 10 min fixed

# CC/CV probe classification (spec: probe-cc-cv-disambiguation).
# Minimum samples before trend classification is attempted.
_MIN_PROBE_SAMPLES = 3
# last_half_mean / first_half_mean below this ratio → CV taper detected.
_CV_FALLING_RATIO = 0.90


def _parse_float(value: str) -> Optional[float]:
    """Parse a HA state string to float; return None for unavailable/non-numeric."""
    if value in ("unavailable", "unknown", "none", ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class HASensorWatcher:
    """Wires HA sensor state changes to the pure-Python coordinator.

    Lifecycle:
      - Construct with hass, coordinator, and entity IDs.
      - Call ``async_start()`` during integration setup to register listeners.
      - Call ``async_stop()`` during integration unload to clean up.
    """

    def __init__(
        self,
        hass: "HomeAssistant",
        coordinator: CyclestewardCoordinator,
        power_entity_id: str,
        plug_entity_id: str,
        temp_entity_id: Optional[str] = None,
        keepalive_interval_s: int = 60,
        profile_store=None,
        target_finish_time: Optional[datetime] = None,
        margin_s: float = _DEFAULT_MARGIN_S,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._power_entity_id = power_entity_id
        self._plug_entity_id = plug_entity_id
        self._temp_entity_id = temp_entity_id
        self._keepalive_interval_s = keepalive_interval_s
        self._profile_store = profile_store

        # Scheduling state (ADR-0012).
        self._target_finish_time: Optional[datetime] = target_finish_time
        self._margin_s: float = margin_s
        self._computed_start_time: Optional[datetime] = None
        self._probe_fired: bool = False          # one probe per charge cycle
        self._probe_soc_reading: Optional[float] = None  # kept for compat; unused in new path
        self._probe_samples: List[Tuple[datetime, float]] = []
        self._overrun_fired: bool = False        # one overrun event per session

        self._cached_power_w: Optional[float] = None
        self._cached_temp_c: Optional[float] = None
        self._meter_blind: bool = False         # latch for meter_unavailable/recovered events
        self._trace_buffer: List[Tuple[datetime, float]] = []
        self._unsubs: list = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Register state-change listeners and keepalive timer."""
        from homeassistant.helpers.event import (
            async_track_state_change_event,
            async_track_time_interval,
        )

        self._unsubs.append(
            async_track_state_change_event(
                self._hass,
                [self._power_entity_id],
                self._handle_power_state_change,
            )
        )

        if self._temp_entity_id:
            self._unsubs.append(
                async_track_state_change_event(
                    self._hass,
                    [self._temp_entity_id],
                    self._handle_temp_state_change,
                )
            )

        self._unsubs.append(
            async_track_time_interval(
                self._hass,
                self._handle_keepalive,
                timedelta(seconds=self._keepalive_interval_s),
            )
        )

    async def async_stop(self) -> None:
        """Unregister all listeners and cancel the keepalive timer."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ── Scheduling helpers ────────────────────────────────────────────────────

    def set_target_finish_time(self, target: Optional[datetime]) -> None:
        """Update the target finish time and reset probe/overrun state for the new cycle."""
        self._target_finish_time = target
        self._probe_fired = False
        self._probe_soc_reading = None
        self._probe_samples.clear()
        self._overrun_fired = False
        self._computed_start_time = self._pessimistic_start_time()

    def _max_duration_s(self) -> float:
        """max = mean + 2×stddev from profile; falls back to pessimistic default."""
        mean_s, uncertainty_s = self._coordinator.profile.estimated_duration_s()
        return mean_s + 2.0 * uncertainty_s

    def _pessimistic_start_time(self) -> Optional[datetime]:
        """Worst-case start = target_finish_time − max_profile_duration − margin."""
        if self._target_finish_time is None:
            return None
        return self._target_finish_time - timedelta(
            seconds=self._max_duration_s() + self._margin_s
        )

    def _probe_time(self) -> Optional[datetime]:
        """probe_time = target_finish_time − max_duration − margin − probe_headroom."""
        if self._target_finish_time is None:
            return None
        return self._target_finish_time - timedelta(
            seconds=self._max_duration_s() + self._margin_s + _PROBE_HEADROOM_S
        )

    # ── Logbook event helper ──────────────────────────────────────────────────

    def _fire_event(self, event: str, reason: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Fire a cyclesteward_event on the HA bus (ADR-0012 transparency)."""
        data: Dict[str, Any] = {
            "event": event,
            "reason": reason,
            "timestamp": _now().isoformat(),
        }
        if extra:
            data.update(extra)
        self._hass.bus.async_fire("cyclesteward_event", data)

    # ── Probe CC/CV classification ────────────────────────────────────────────

    def _classify_probe_trend(self) -> Optional[str]:
        """Classify the accumulated probe window as 'cc' or 'cv_taper'.

        Returns None when fewer than _MIN_PROBE_SAMPLES are available.
        Compares the mean of the last half of samples to the mean of the first
        half: a ratio below _CV_FALLING_RATIO indicates CV taper (falling).
        """
        watts = [w for _, w in self._probe_samples]
        n = len(watts)
        if n < _MIN_PROBE_SAMPLES:
            return None
        half = n // 2
        first_mean = sum(watts[:half]) / half
        last_mean = sum(watts[-half:]) / half
        if first_mean == 0.0:
            return "cc"
        return "cc" if last_mean / first_mean >= _CV_FALLING_RATIO else "cv_taper"

    def _apply_cc_probe_result(self, now: datetime) -> None:
        """Update computed_start_time using the CC-phase wattage from the probe window."""
        watts = [w for _, w in self._probe_samples]
        half = len(watts) // 2
        representative_w = sum(watts[-half:]) / half

        soc_est = self._coordinator._controller.estimate_soc(
            representative_w, self._cached_temp_c
        )
        if (
            soc_est is not None
            and not soc_est.low_confidence
            and self._target_finish_time is not None
        ):
            profile = self._coordinator.profile
            mean_dur_s, _ = profile.estimated_duration_s()
            remaining_frac = max(0.0, 1.0 - soc_est.estimated_soc_pct / 100.0)
            self._computed_start_time = self._target_finish_time - timedelta(
                seconds=mean_dur_s * remaining_frac + self._margin_s
            )
            self._fire_event(
                "probe_result",
                f"probe complete: CC phase; SoC ~{soc_est.estimated_soc_pct:.0f}%; start time updated",
                {
                    "classification": "cc",
                    "soc_estimate_pct": soc_est.estimated_soc_pct,
                    "uncertainty_pct": soc_est.uncertainty_pct,
                    "computed_start_time": self._computed_start_time.isoformat(),
                },
            )
        else:
            self._fire_event(
                "probe_result",
                "probe complete: CC phase; SoC estimate low-confidence; using pessimistic start time",
                {
                    "classification": "cc",
                    "computed_start_time": (
                        self._computed_start_time.isoformat()
                        if self._computed_start_time else None
                    ),
                },
            )

    def _apply_cv_taper_probe_result(self) -> None:
        """Push computed_start_time late; battery near-full."""
        watts = [w for _, w in self._probe_samples]
        half = len(watts) // 2
        first_mean = sum(watts[:half]) / half
        last_mean = sum(watts[-half:]) / half
        if self._target_finish_time is not None:
            self._computed_start_time = self._target_finish_time - timedelta(
                seconds=self._margin_s
            )
        self._fire_event(
            "probe_result",
            "probe complete: CV taper detected; battery near-full; start time pushed late",
            {
                "classification": "cv_taper",
                "first_mean_w": round(first_mean, 1),
                "last_mean_w": round(last_mean, 1),
                "computed_start_time": (
                    self._computed_start_time.isoformat()
                    if self._computed_start_time else None
                ),
            },
        )

    # ── Core tick logic ───────────────────────────────────────────────────────

    def _plug_is_on(self) -> Optional[bool]:
        """Read current plug state from HA at tick time."""
        state = self._hass.states.get(self._plug_entity_id)
        if state is None:
            return None
        if state.state == "on":
            return True
        if state.state == "off":
            return False
        return None

    async def _do_tick(self, power_w: Optional[float], now: datetime) -> None:
        """Call coordinator.tick(), manage trace buffer, dispatch relay action."""
        prev_state = self._coordinator.session_state

        # Meter availability breadcrumbs (spec stale-meter-guardrail): a one-shot
        # logbook event on the numeric↔None transition while charging.  These are
        # observability only — the STALE_METER fault is decided in the pure core.
        if prev_state == SessionState.CHARGING:
            if power_w is None and not self._meter_blind:
                self._meter_blind = True
                self._fire_event(
                    "meter_unavailable",
                    "power meter unavailable; holding (will fault if prolonged)",
                )
            elif power_w is not None and self._meter_blind:
                self._meter_blind = False
                self._fire_event("meter_recovered", "power meter reading resumed")

        # ── Probe scheduling (ADR-0012 B) ─────────────────────────────────────
        # Fire the probe once per cycle when the clock reaches probe_time.
        if (
            not self._probe_fired
            and self._target_finish_time is not None
            and prev_state == SessionState.WAITING_FOR_SCHEDULE
        ):
            pt = self._probe_time()
            if pt is not None and now >= pt:
                self._probe_fired = True
                # start_probe can refuse (relay guardrail suppression); never
                # energize the plug on a refusal — fall back to the pessimistic
                # start time already in place.
                if self._coordinator.start_probe(now):
                    self._probe_samples.clear()
                    self._fire_event(
                        "probe_start",
                        "Probing: estimating SoC (≤5 min)",
                        {"expected_duration_s": self._coordinator._controller._config.max_probe_seconds},
                    )
                    await self._hass.services.async_call(
                        "homeassistant", "turn_on", {"entity_id": self._plug_entity_id}
                    )
                else:
                    self._fire_event(
                        "probe_result",
                        "probe refused by relay guardrail; using pessimistic start time",
                        {"computed_start_time": (self._computed_start_time.isoformat()
                                                 if self._computed_start_time else None)},
                    )
                return

        # ── Probe reading accumulation and CC/CV classification ───────────────
        # Accumulate wattage samples during PROBING.  Once _MIN_PROBE_SAMPLES
        # are collected, classify the trend as CC or CV taper and conclude the
        # probe early.  If the controller times out first, classify whatever
        # samples exist before falling back to the pessimistic start time.
        if prev_state == SessionState.PROBING:
            result = self._coordinator.tick(
                power_w,
                self._cached_temp_c,
                now,
                plug_is_on=self._plug_is_on(),
                computed_start_time=self._computed_start_time,
            )

            if result.action == SessionAction.TURN_OFF:
                # Controller timed out; turn off the plug.
                await self._hass.services.async_call(
                    "homeassistant", "turn_off", {"entity_id": self._plug_entity_id}
                )
                # Classify whatever samples we have (may still be sufficient).
                classification = self._classify_probe_trend()
                if classification == "cv_taper":
                    self._apply_cv_taper_probe_result()
                elif classification == "cc":
                    self._apply_cc_probe_result(now)
                else:
                    self._fire_event(
                        "probe_result",
                        "probe timeout: insufficient samples; using pessimistic start time",
                        {"computed_start_time": (self._computed_start_time.isoformat()
                                                 if self._computed_start_time else None)},
                    )
                self._probe_samples.clear()
                return

            # Accumulate this tick's sample.
            if power_w is not None:
                self._probe_samples.append((now, power_w))

            # Classify once enough samples are available; conclude probe early.
            classification = self._classify_probe_trend()
            if classification is not None:
                self._coordinator.end_probe(now)
                await self._hass.services.async_call(
                    "homeassistant", "turn_off", {"entity_id": self._plug_entity_id}
                )
                if classification == "cv_taper":
                    self._apply_cv_taper_probe_result()
                else:
                    self._apply_cc_probe_result(now)
                self._probe_samples.clear()
            return

        # ── Normal tick ────────────────────────────────────────────────────────
        result = self._coordinator.tick(
            power_w,
            self._cached_temp_c,
            now,
            plug_is_on=self._plug_is_on(),
            computed_start_time=self._computed_start_time,
        )

        current_state = self._coordinator.session_state

        # Clear trace buffer and reset per-cycle scheduling state on new session.
        if prev_state != SessionState.CHARGING and current_state == SessionState.CHARGING:
            self._trace_buffer.clear()
            self._fire_event(
                "session_start",
                self._coordinator.session_reason or "Charging started",
                {"target_finish_time": (self._target_finish_time.isoformat()
                                        if self._target_finish_time else None)},
            )

        # Accumulate valid power readings for calibration.
        if power_w is not None:
            self._trace_buffer.append((now, power_w))

        # Overrun detection (ADR-0012 C): fire once per session when still
        # CHARGING after target_finish_time.
        if (
            current_state == SessionState.CHARGING
            and self._target_finish_time is not None
            and now > self._target_finish_time
            and not self._overrun_fired
        ):
            self._overrun_fired = True
            self._fire_event(
                "overrun",
                "Charge session running past target finish time",
                {"target_finish_time": self._target_finish_time.isoformat()},
            )

        # Relay dispatch.
        if result.action == SessionAction.TURN_ON:
            await self._hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": self._plug_entity_id}
            )
        elif result.action == SessionAction.TURN_OFF:
            await self._hass.services.async_call(
                "homeassistant", "turn_off", {"entity_id": self._plug_entity_id}
            )

        # Taper-floor calibration ingestion (slice 3).
        if (
            prev_state == SessionState.CHARGING
            and current_state == SessionState.DONE_LATCHED_OFF
            and self._coordinator.charge_mode == ChargeMode.CHARGE_TO_FULL
            and "taper floor" in self._coordinator.session_reason
            and self._profile_store is not None
        ):
            updated = self._coordinator.ingest_from_trace(
                list(self._trace_buffer),
                session_temp_c=self._cached_temp_c,
            )
            await self._profile_store.async_save_profile(
                self._profile_store.active_battery_id, updated
            )

        # Reset per-cycle state when a charge session completes so the next
        # scheduled session gets a fresh probe and overrun guard.
        if current_state in (SessionState.DONE_LATCHED_OFF, SessionState.IDLE):
            self._probe_fired = False
            self._probe_soc_reading = None
            self._probe_samples.clear()
            self._overrun_fired = False
            self._meter_blind = False

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle_power_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        power_w = _parse_float(new_state.state)
        self._cached_power_w = power_w
        await self._do_tick(power_w, _now())

    async def _handle_temp_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._cached_temp_c = _parse_float(new_state.state)

    async def _handle_keepalive(self, now: datetime) -> None:
        await self._do_tick(self._cached_power_w, now)

    # ── Public read access ────────────────────────────────────────────────────

    @property
    def trace_buffer(self) -> List[Tuple[datetime, float]]:
        """Snapshot of the accumulated live power trace for the current session."""
        return list(self._trace_buffer)

    @property
    def computed_start_time(self) -> Optional[datetime]:
        """Current derived charge start time (None until target_finish_time is set)."""
        return self._computed_start_time
