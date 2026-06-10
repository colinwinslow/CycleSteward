"""Pure-Python coordinator for CycleSteward.

No homeassistant imports.  Wraps SessionController and exposes the entity-facing
API: readable properties for all entity states, tick(), mode controls, and a
listener-subscription mechanism so HA entities receive state-change notifications.

HA entities read from coordinator properties and write via coordinator methods;
they register a listener via subscribe() to receive schedule_update_ha_state()
calls.  The coordinator carries no derived state of its own beyond what
SessionController already maintains (ADR-0006).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

from cyclesteward.calibration import CalibrationProfile
from cyclesteward.guardrails import GuardrailFault, GuardrailsConfig
from cyclesteward.session_control import (
    ChargeMode,
    SessionConfig,
    SessionController,
    SessionState,
    SocEstimate,
    TemperatureConfig,
    TickResult,
)


class CyclestewardCoordinator:
    """Wraps SessionController; no HA imports.

    Lifecycle:
      - Construct with a CalibrationProfile and optional config objects.
      - Call tick() on each polling interval, passing current sensor readings.
      - Call set_mode() / manual_override_on() / acknowledge_fault() from HA
        entity write handlers.
      - Register listeners via subscribe(); they are called after every state
        change so HA entities can push updates to the frontend.
    """

    def __init__(
        self,
        profile: CalibrationProfile,
        config: Optional[SessionConfig] = None,
        temp_config: Optional[TemperatureConfig] = None,
        guardrails_config: Optional[GuardrailsConfig] = None,
    ) -> None:
        self._controller = SessionController(
            profile, config, temp_config, guardrails_config
        )
        self._last_result: Optional[TickResult] = None
        self._listeners: List[Callable[[], None]] = []

    # ── Read properties ───────────────────────────────────────────────────────

    @property
    def charge_mode(self) -> ChargeMode:
        return self._controller.mode

    @property
    def session_state(self) -> SessionState:
        return self._controller.state

    @property
    def last_tick_result(self) -> Optional[TickResult]:
        return self._last_result

    @property
    def soc_estimate(self) -> Optional[SocEstimate]:
        if self._last_result is None:
            return None
        return self._last_result.soc_estimate

    @property
    def active_fault(self) -> Optional[GuardrailFault]:
        if self._last_result is None:
            return None
        return self._last_result.fault

    @property
    def session_reason(self) -> str:
        """Human-readable reason for the current state (ADR-0012 transparency)."""
        if self._last_result is None:
            return ""
        return self._last_result.reason

    @property
    def active_wh(self) -> float:
        return self._controller.active_wh

    @property
    def relay_cycle_count(self) -> int:
        return self._controller.relay_cycle_count

    @property
    def session_start(self) -> Optional[datetime]:
        return self._controller.session_start

    @property
    def target_wattage(self) -> Optional[float]:
        return self._controller.target_wattage

    # ── Write methods ─────────────────────────────────────────────────────────

    def set_mode(self, mode: ChargeMode) -> None:
        self._controller.set_mode(mode)
        self._notify()

    def manual_override_on(self) -> None:
        self._controller.manual_override_on()
        self._notify()

    def acknowledge_fault(self) -> bool:
        """Clear a non-terminal fault and return to IDLE.

        Returns True if a fault was cleared; False if there was nothing to clear.
        FREEZE_LOCKOUT does not produce a FAULTED state so this path is not
        reached for temperature lock-outs (the controller stays IDLE).
        """
        if self._controller.state != SessionState.FAULTED:
            return False
        self._controller.set_mode(ChargeMode.OFF)
        self._notify()
        return True

    def tick(
        self,
        power_w: Optional[float],
        temperature_c: Optional[float],
        now: datetime,
        *,
        plug_is_on: Optional[bool] = None,
    ) -> TickResult:
        """Advance one sample period and return the action to take.

        Callers should act on TickResult.action (TURN_ON / TURN_OFF / NONE)
        immediately.  The coordinator stores the result and notifies listeners.
        """
        result = self._controller.tick(
            power_w, temperature_c, now, plug_is_on=plug_is_on
        )
        self._last_result = result
        self._notify()
        return result

    # ── Listener management ───────────────────────────────────────────────────

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener called after every tick or mode change.

        Returns an unsubscribe callable.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
