"""Session-control state machine: charge-to-target, scheduling, cutoff, and SoC estimation.

Implements the pure core of ADR-0002 (wattage-anchor SoC model), ADR-0005
(automation guardrails), ADR-0008 (temperature gating and compensation), and
ADR-0009 (modes/scheduling/safe defaults).  All I/O is injected; this module
has no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional

from .calibration import CalibrationProfile, ProfileState, SocAssumptions
from .guardrails import GuardrailEvaluator, GuardrailFault, GuardrailsConfig


class ChargeMode(str, Enum):
    OFF = "off"
    CHARGE_TO_TARGET = "charge_to_target"
    CHARGE_TO_FULL = "charge_to_full"


class SessionState(str, Enum):
    IDLE = "idle"
    WAITING_FOR_SCHEDULE = "waiting_for_schedule"
    PROBING = "probing"
    HEAT_DELAY = "heat_delay"
    CHARGING = "charging"
    DONE_LATCHED_OFF = "done_latched_off"
    FAULTED = "faulted"


class SessionAction(str, Enum):
    NONE = "none"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


@dataclass
class SocEstimate:
    """SoC estimated from instantaneous CC-phase wattage (ADR-0002).

    Always labeled as estimated; carries uncertainty when calibration is coarse.
    """

    estimated_soc_pct: float
    uncertainty_pct: float
    low_confidence: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "estimated_soc_pct": self.estimated_soc_pct,
            "uncertainty_pct": self.uncertainty_pct,
            "low_confidence": self.low_confidence,
            "note": self.note,
        }


@dataclass
class TickResult:
    """Result of one controller tick: action, new state, optional SoC, reason, and optional fault."""

    action: SessionAction
    state: SessionState
    soc_estimate: Optional[SocEstimate]
    reason: str
    fault: Optional[GuardrailFault] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "action": self.action.value,
            "state": self.state.value,
            "soc_estimate": self.soc_estimate.to_dict() if self.soc_estimate else None,
            "reason": self.reason,
        }
        if self.fault is not None:
            d["fault"] = self.fault.value
        return d


@dataclass
class TemperatureConfig:
    """Temperature gating and compensation configuration (ADR-0008).

    All thresholds are configurable; defaults are conservative starting points.
    Set ``temp_coeff_w_per_c = 0`` (default) to disable compensation entirely.
    """

    freeze_threshold_c: float = 0.0
    heat_delay_threshold_c: float = 35.0
    sensor_offset_c: float = 0.0
    temp_coeff_w_per_c: float = 0.0
    baseline_temp_c: float = 20.0
    heat_delay_deadline_seconds: float = 3600.0


@dataclass
class SessionConfig:
    """Session controller configuration (ADR-0009)."""

    target_soc_pct: float = 80.0
    scheduled_start: Optional[time] = None
    morning_reset_time: time = field(default_factory=lambda: time(6, 0))
    taper_below_floor_seconds: float = 300.0
    max_probe_seconds: float = 300.0


class SessionController:
    """Pure state machine for charge-session control.

    No Home Assistant imports.  Inject a ``CalibrationProfile`` and call
    ``tick()`` each sample period to receive an action and new state.

    State machine (normal path):
      IDLE ──(mode set, no schedule)──► CHARGING ──(threshold crossed)──► DONE_LATCHED_OFF
      IDLE ──(mode set, future schedule)──► WAITING_FOR_SCHEDULE ──(time arrived)──► CHARGING
      WAITING_FOR_SCHEDULE ──(start_probe called)──► PROBING ──(done/timeout)──► WAITING_FOR_SCHEDULE
      IDLE ──(temperature too hot)──► HEAT_DELAY ──(cooled)──► IDLE ──► CHARGING
      Any state ──(morning reset)──► IDLE (mode cleared)
      Any state ──(guardrail fault)──► FAULTED (requires explicit user action to resume)
    """

    def __init__(
        self,
        profile: CalibrationProfile,
        config: Optional[SessionConfig] = None,
        temp_config: Optional[TemperatureConfig] = None,
        guardrails_config: Optional[GuardrailsConfig] = None,
    ) -> None:
        self._profile = profile
        self._config = config or SessionConfig()
        self._temp_config = temp_config or TemperatureConfig()
        self._guardrails_config = guardrails_config or GuardrailsConfig()
        self._guardrails = GuardrailEvaluator(self._guardrails_config)

        self._mode: ChargeMode = ChargeMode.OFF
        self._state: SessionState = SessionState.IDLE

        self._last_morning_reset: Optional[datetime] = None
        self._heat_delay_start: Optional[datetime] = None
        self._taper_start: Optional[datetime] = None
        self._probe_start: Optional[datetime] = None

        self.event_log: List[str] = []

    @property
    def mode(self) -> ChargeMode:
        return self._mode

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def active_wh(self) -> float:
        return self._guardrails.active_wh

    @property
    def relay_cycle_count(self) -> int:
        return self._guardrails.relay_cycle_count

    @property
    def session_start(self) -> Optional[datetime]:
        return self._guardrails.session_start

    @property
    def target_wattage(self) -> Optional[float]:
        return self._profile.target_wattage(self._config.target_soc_pct)

    def set_mode(self, mode: ChargeMode) -> None:
        """Set charge mode.  Modes are mutually exclusive; setting one clears the other.

        Resets to IDLE so a new session begins on the next tick.
        """
        self._mode = mode
        self._state = SessionState.IDLE
        self._taper_start = None
        self._heat_delay_start = None
        self._guardrails.reset()

    def manual_override_on(self) -> None:
        """User manually turns the plug on.

        If an active mode is set, this transitions directly to CHARGING so the
        cutoff evaluator still applies on every subsequent tick (ADR-0009).
        Guardrail session-start is lazy-initialised on the first CHARGING tick.
        """
        if self._mode in (ChargeMode.CHARGE_TO_TARGET, ChargeMode.CHARGE_TO_FULL):
            self._state = SessionState.CHARGING

    def start_probe(self, now: datetime) -> bool:
        """Begin a SoC-estimation probe (ADR-0012 decision B).

        Transitions WAITING_FOR_SCHEDULE → PROBING and issues TURN_ON.
        Returns True if the transition happened, False if the state was wrong.
        """
        if self._state != SessionState.WAITING_FOR_SCHEDULE:
            return False
        self._state = SessionState.PROBING
        self._probe_start = now
        return True

    def end_probe(self) -> bool:
        """Conclude an active probe and return to WAITING_FOR_SCHEDULE.

        Called by the adapter when a usable wattage reading has been obtained
        or the probe is being abandoned.  Returns True if a transition happened.
        """
        if self._state != SessionState.PROBING:
            return False
        self._state = SessionState.WAITING_FOR_SCHEDULE
        self._probe_start = None
        return True

    def tick(
        self,
        power_w: Optional[float],
        temperature_c: Optional[float],
        now: datetime,
        *,
        plug_is_on: Optional[bool] = None,
        computed_start_time: Optional[datetime] = None,
    ) -> TickResult:
        """Evaluate one sample and return the action to take.

        ``power_w`` and ``temperature_c`` may be ``None`` (unknown/unavailable).
        ``plug_is_on`` is the observed smart-plug state; used to confirm TURN_OFF
        commands.  Pass ``None`` when the plug state is not known.
        ``computed_start_time`` is the adapter-derived datetime to begin charging
        (ADR-0012 D); if supplied it replaces the time-of-day ``scheduled_start``
        check while in ``WAITING_FOR_SCHEDULE``.

        The controller defaults safely on missing readings (hold, no cutoff misfire).
        """
        # 1. Morning reset: once per day past the configured time, clear mode → IDLE.
        if self._should_morning_reset(now):
            self._last_morning_reset = self._today_reset_dt(now)
            if self._state != SessionState.FAULTED:
                self._mode = ChargeMode.OFF
                self._state = SessionState.IDLE
                self._taper_start = None
                self._heat_delay_start = None
                self._guardrails.reset()
                return TickResult(
                    SessionAction.NONE, SessionState.IDLE, None,
                    "morning reset: modes cleared"
                )

        # 2. Command confirmation: fires before terminal-state short-circuits so
        #    a DONE_LATCHED_OFF session can still be faulted if the plug ignores
        #    the TURN_OFF command.
        if self._state != SessionState.FAULTED:
            cmd_guard = self._guardrails.check_command_confirmation(plug_is_on, now)
            if cmd_guard is not None:
                self._state = SessionState.FAULTED
                self.event_log.append(
                    f"guardrail/{cmd_guard.fault.value}: {cmd_guard.reason}"
                )
                return TickResult(
                    SessionAction.NONE,
                    SessionState.FAULTED,
                    None,
                    cmd_guard.reason,
                    fault=cmd_guard.fault,
                )

        # 3. Mode off → stay idle (preserve DONE_LATCHED_OFF / FAULTED as-is).
        if self._mode == ChargeMode.OFF:
            if self._state not in (SessionState.DONE_LATCHED_OFF, SessionState.FAULTED):
                self._state = SessionState.IDLE
            return TickResult(SessionAction.NONE, self._state, None, "mode off")

        # 4. Terminal states: latch and fault hold until explicit action.
        if self._state == SessionState.DONE_LATCHED_OFF:
            return TickResult(
                SessionAction.NONE, SessionState.DONE_LATCHED_OFF, None,
                "latched off; awaiting new session"
            )
        if self._state == SessionState.FAULTED:
            return TickResult(
                SessionAction.NONE, SessionState.FAULTED, None,
                "faulted; awaiting user action"
            )

        # 5. Probing: handled before the power-null guard so probe timeout fires
        #    even when the meter is temporarily unavailable (ADR-0012 B).
        #    The relay is already on (start_probe() issued TURN_ON via adapter).
        if self._state == SessionState.PROBING:
            # Probe timeout: fall back to WAITING_FOR_SCHEDULE; adapter will use
            # the pessimistic computed_start_time (ADR-0012 B fallback).
            if (
                self._probe_start is not None
                and (now - self._probe_start).total_seconds()
                >= self._config.max_probe_seconds
            ):
                self._state = SessionState.WAITING_FOR_SCHEDULE
                self._probe_start = None
                soc_est = (
                    self._estimate_soc(power_w, temperature_c)
                    if power_w is not None
                    else None
                )
                return TickResult(
                    SessionAction.TURN_OFF,
                    SessionState.WAITING_FOR_SCHEDULE,
                    soc_est,
                    "probe timeout: returning to schedule; using pessimistic start time",
                )
            if power_w is None:
                return TickResult(
                    SessionAction.NONE, SessionState.PROBING, None,
                    "Probing: estimating SoC (≤5 min)"
                )
            # Accumulate Wh during probe so energy consumed counts toward the
            # guardrail on the subsequent CHARGING session (ADR-0005 invariant 7).
            idle_w = self._profile.idle_power_w or 0.0
            self._guardrails.accumulate(power_w, idle_w, now)
            soc_est = self._estimate_soc(power_w, temperature_c)
            return TickResult(
                SessionAction.NONE, SessionState.PROBING, soc_est,
                "Probing: estimating SoC (≤5 min)"
            )

        # 6. Missing/non-numeric power: hold safely, no progress, no cutoff misfire.
        if power_w is None:
            return TickResult(
                SessionAction.NONE, self._state, None,
                "power reading unavailable; holding"
            )

        # 7. Temperature gate (applies before starting a new charge).
        if self._state in (
            SessionState.IDLE,
            SessionState.WAITING_FOR_SCHEDULE,
            SessionState.HEAT_DELAY,
        ):
            gate = self._temperature_gate(temperature_c, now)
            if gate is not None:
                return gate

        # 7. Schedule check: if an active mode is set and we are not yet charging,
        #    check whether to wait or start.
        if self._state in (SessionState.IDLE, SessionState.WAITING_FOR_SCHEDULE):
            # ADR-0012 D: computed_start_time (adapter-derived datetime) takes
            # precedence over the legacy time-of-day scheduled_start when supplied.
            if computed_start_time is not None:
                if now < computed_start_time:
                    self._state = SessionState.WAITING_FOR_SCHEDULE
                    return TickResult(
                        SessionAction.NONE, SessionState.WAITING_FOR_SCHEDULE, None,
                        f"Scheduled: waiting for start time (target {computed_start_time.strftime('%H:%M')})"
                    )
            elif self._config.scheduled_start is not None:
                if now.time() < self._config.scheduled_start:
                    self._state = SessionState.WAITING_FOR_SCHEDULE
                    return TickResult(
                        SessionAction.NONE, SessionState.WAITING_FOR_SCHEDULE, None,
                        f"Scheduled: waiting for start time (target {self._config.scheduled_start})"
                    )
            # No schedule, or past the scheduled start time: begin charging.
            self._state = SessionState.CHARGING
            self._guardrails.on_charging_started(now)
            return TickResult(
                SessionAction.TURN_ON, SessionState.CHARGING, None, "starting charge"
            )

        # 8. Charging: run guardrails, then evaluate the cutoff for the active mode.
        if self._state == SessionState.CHARGING:
            idle_w = self._profile.idle_power_w or 0.0
            self._guardrails.accumulate(power_w, idle_w, now)

            # Guardrail A: max runtime.
            rt_guard = self._guardrails.check_runtime(now)
            if rt_guard is not None:
                self._state = SessionState.FAULTED
                self.event_log.append(
                    f"guardrail/{rt_guard.fault.value}: {rt_guard.reason}"
                )
                return TickResult(
                    SessionAction.TURN_OFF,
                    SessionState.FAULTED,
                    None,
                    rt_guard.reason,
                    fault=rt_guard.fault,
                )

            # Guardrail B: max active Wh.
            effective_max_wh = self._guardrails_config.max_active_wh
            if effective_max_wh is None and self._profile.active_full_wh is not None:
                effective_max_wh = self._profile.active_full_wh * 1.2
            wh_guard = self._guardrails.check_active_wh(effective_max_wh)
            if wh_guard is not None:
                self._state = SessionState.FAULTED
                self.event_log.append(
                    f"guardrail/{wh_guard.fault.value}: {wh_guard.reason}"
                )
                return TickResult(
                    SessionAction.TURN_OFF,
                    SessionState.FAULTED,
                    None,
                    wh_guard.reason,
                    fault=wh_guard.fault,
                )

            soc_est = self._estimate_soc(power_w, temperature_c)

            if self._mode == ChargeMode.CHARGE_TO_TARGET:
                target = self._adjusted_target_wattage(temperature_c)
                if target is not None and power_w >= target:
                    # Guardrail C: relay chatter check before committing TURN_OFF.
                    relay_guard = self._guardrails.check_relay(True, now)
                    if relay_guard is not None:
                        self.event_log.append(
                            f"guardrail/{relay_guard.fault.value}: {relay_guard.reason}"
                        )
                        return TickResult(
                            SessionAction.NONE,
                            SessionState.CHARGING,
                            soc_est,
                            f"relay suppressed: {relay_guard.reason}",
                            fault=relay_guard.fault,
                        )
                    self._guardrails.on_turn_off_committed(now)
                    self._state = SessionState.DONE_LATCHED_OFF
                    return TickResult(
                        SessionAction.TURN_OFF,
                        SessionState.DONE_LATCHED_OFF,
                        soc_est,
                        f"wattage {power_w:.1f} W >= target {target:.1f} W; cutoff",
                    )
                return TickResult(
                    SessionAction.NONE, SessionState.CHARGING, soc_est, "charging"
                )

            if self._mode == ChargeMode.CHARGE_TO_FULL:
                taper_floor = self._profile.taper_floor_w
                if taper_floor is not None and power_w < taper_floor:
                    if self._taper_start is None:
                        self._taper_start = now
                    elif (
                        (now - self._taper_start).total_seconds()
                        >= self._config.taper_below_floor_seconds
                    ):
                        # Guardrail C: relay chatter check before committing TURN_OFF.
                        relay_guard = self._guardrails.check_relay(True, now)
                        if relay_guard is not None:
                            self.event_log.append(
                                f"guardrail/{relay_guard.fault.value}: {relay_guard.reason}"
                            )
                            return TickResult(
                                SessionAction.NONE,
                                SessionState.CHARGING,
                                soc_est,
                                f"relay suppressed: {relay_guard.reason}",
                                fault=relay_guard.fault,
                            )
                        self._guardrails.on_turn_off_committed(now)
                        self._state = SessionState.DONE_LATCHED_OFF
                        return TickResult(
                            SessionAction.TURN_OFF,
                            SessionState.DONE_LATCHED_OFF,
                            soc_est,
                            "wattage below taper floor for configured duration; "
                            "best-effort full completion",
                        )
                else:
                    self._taper_start = None
                return TickResult(
                    SessionAction.NONE, SessionState.CHARGING, soc_est,
                    "charging to full"
                )

        return TickResult(SessionAction.NONE, self._state, None, "no action")

    def estimate_soc(
        self, power_w: float, temperature_c: Optional[float] = None
    ) -> Optional[SocEstimate]:
        """Estimate SoC from instantaneous CC-phase wattage (public API)."""
        return self._estimate_soc(power_w, temperature_c)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _should_morning_reset(self, now: datetime) -> bool:
        today_reset = self._today_reset_dt(now)
        if now >= today_reset:
            if (
                self._last_morning_reset is None
                or self._last_morning_reset < today_reset
            ):
                return True
        return False

    def _today_reset_dt(self, now: datetime) -> datetime:
        rt = self._config.morning_reset_time
        return now.replace(hour=rt.hour, minute=rt.minute, second=0, microsecond=0)

    def _temperature_gate(
        self, temperature_c: Optional[float], now: datetime
    ) -> Optional[TickResult]:
        if temperature_c is None:
            # No sensor configured: proceed uncompensated and ungated (ADR-0008).
            return None

        effective = temperature_c + self._temp_config.sensor_offset_c

        if effective < self._temp_config.freeze_threshold_c:
            # Hard stop: refuse to start charging below the freeze threshold.
            self._state = SessionState.IDLE
            reason = (
                f"freeze lockout: {effective:.1f} °C < "
                f"{self._temp_config.freeze_threshold_c:.1f} °C"
            )
            return TickResult(SessionAction.NONE, SessionState.IDLE, None, reason)

        if effective > self._temp_config.heat_delay_threshold_c:
            # Heat delay: hold in a non-fault waiting state; retry when cooled.
            if self._state != SessionState.HEAT_DELAY:
                self._heat_delay_start = now
                self._state = SessionState.HEAT_DELAY
            if self._heat_delay_start is not None:
                elapsed = (now - self._heat_delay_start).total_seconds()
                if elapsed >= self._temp_config.heat_delay_deadline_seconds:
                    self._mode = ChargeMode.OFF
                    self._state = SessionState.IDLE
                    reason = (
                        f"heat delay deadline exceeded after {elapsed:.0f} s; "
                        "session skipped, mode reset to off"
                    )
                    return TickResult(SessionAction.NONE, SessionState.IDLE, None, reason)
            reason = (
                f"heat delay: {effective:.1f} °C > "
                f"{self._temp_config.heat_delay_threshold_c:.1f} °C"
            )
            return TickResult(SessionAction.NONE, SessionState.HEAT_DELAY, None, reason)

        # Temperature OK: if we were in heat delay, clear it and fall through.
        if self._state == SessionState.HEAT_DELAY:
            self._heat_delay_start = None
            self._state = SessionState.IDLE

        return None

    def _adjusted_target_wattage(self, temperature_c: Optional[float]) -> Optional[float]:
        base = self._profile.target_wattage(self._config.target_soc_pct)
        if base is None:
            return None
        if temperature_c is None or self._temp_config.temp_coeff_w_per_c == 0:
            return base
        return base + self._temp_config.temp_coeff_w_per_c * (
            temperature_c - self._temp_config.baseline_temp_c
        )

    def _estimate_soc(
        self, power_w: float, temperature_c: Optional[float]
    ) -> Optional[SocEstimate]:
        if self._profile.watts_at_low is None or self._profile.watts_at_transition is None:
            return SocEstimate(0.0, 50.0, True, "profile not calibrated")

        asm = self._profile.assumptions or SocAssumptions()
        w_low = self._temp_shift(self._profile.watts_at_low.watts, temperature_c)
        w_trans = self._temp_shift(self._profile.watts_at_transition.watts, temperature_c)
        w_span = w_trans - w_low
        if w_span <= 0:
            return SocEstimate(0.0, 50.0, True, "wattage anchor span is zero")

        soc_span = asm.soc_at_transition_pct - asm.soc_at_low_pct
        t = (power_w - w_low) / w_span
        soc = asm.soc_at_low_pct + t * soc_span
        soc = max(0.0, min(100.0, soc))

        low_confidence = self._profile.state != ProfileState.CALIBRATED
        uncertainty = 20.0 if low_confidence else 10.0
        note = ""

        if power_w >= w_trans:
            # In or past CV phase; wattage model no longer reliable for SoC.
            soc = asm.soc_at_transition_pct
            note = "above CC/CV transition; model less reliable"
            uncertainty = 15.0
            low_confidence = True

        if temperature_c is not None and self._temp_config.temp_coeff_w_per_c != 0:
            note = f"{note}; temperature-compensated" if note else "temperature-compensated"

        return SocEstimate(round(soc, 1), uncertainty, low_confidence, note)

    def _temp_shift(self, base_watts: float, temperature_c: Optional[float]) -> float:
        if temperature_c is None or self._temp_config.temp_coeff_w_per_c == 0:
            return base_watts
        return base_watts + self._temp_config.temp_coeff_w_per_c * (
            temperature_c - self._temp_config.baseline_temp_c
        )
