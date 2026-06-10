"""HA sensor watcher: bridges real HA state-change events to the pure coordinator.

``HASensorWatcher`` subscribes to HA state-changed events for the configured
power and (optionally) temperature entities, drives ``CyclestewardCoordinator.tick()``
on each power update and on a keepalive timer, and dispatches relay actions by
calling HA services on the configured plug entity.

A live power trace ``(timestamp, power_w)`` is accumulated during each session.
The buffer is cleared when a new session starts (CHARGING state entry) and
retained through DONE_LATCHED_OFF so slice 3 can read it for calibration.

All HA imports are deferred to ``async_start()`` call time so the module can
be imported in tests without a real HA runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from cyclesteward.session_control import SessionAction, SessionState

from .coordinator import CyclestewardCoordinator


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
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._power_entity_id = power_entity_id
        self._plug_entity_id = plug_entity_id
        self._temp_entity_id = temp_entity_id
        self._keepalive_interval_s = keepalive_interval_s

        self._cached_power_w: Optional[float] = None
        self._cached_temp_c: Optional[float] = None
        self._trace_buffer: List[Tuple[datetime, float]] = []
        self._unsubs: list = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Register state-change listeners and keepalive timer."""
        from datetime import timedelta

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

        result = self._coordinator.tick(
            power_w,
            self._cached_temp_c,
            now,
            plug_is_on=self._plug_is_on(),
        )

        current_state = self._coordinator.session_state

        # Clear trace buffer on new session start.
        if prev_state != SessionState.CHARGING and current_state == SessionState.CHARGING:
            self._trace_buffer.clear()

        # Accumulate valid power readings for slice 3 calibration.
        if power_w is not None:
            self._trace_buffer.append((now, power_w))

        # Relay dispatch.
        if result.action == SessionAction.TURN_ON:
            await self._hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": self._plug_entity_id}
            )
        elif result.action == SessionAction.TURN_OFF:
            await self._hass.services.async_call(
                "homeassistant", "turn_off", {"entity_id": self._plug_entity_id}
            )

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
