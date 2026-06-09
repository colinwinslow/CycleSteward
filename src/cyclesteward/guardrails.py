"""Automation guardrails for charge sessions (ADR-0005).

Detects:
  - maximum session runtime exceeded (scenario A)
  - maximum active Wh exceeded (scenario B)
  - relay cycle limit or minimum dwell violation (scenario C)
  - switch command not confirmed by the plug (scenario D)

Temperature gating (freeze lockout, heat delay) and missing-reading safety are
enforced in the session-control state machine itself (scenarios E/F/G).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional


class GuardrailFault(str, Enum):
    MAX_RUNTIME = "max_runtime"
    MAX_ACTIVE_WH = "max_active_wh"
    RELAY_LIMIT = "relay_limit"
    MIN_DWELL = "min_dwell"
    SWITCH_COMMAND_FAILURE = "switch_command_failure"


@dataclass
class GuardrailsConfig:
    """Configuration for all automation guardrails (ADR-0005)."""

    max_runtime_seconds: float = 28800.0  # 8 hours
    max_active_wh: Optional[float] = None  # None → derive limit from profile at runtime
    relay_cycle_limit: int = 10  # max total relay transitions per session
    min_dwell_seconds: float = 30.0  # min seconds between relay operations
    command_confirm_seconds: float = 10.0  # seconds to wait for plug to confirm off


@dataclass
class GuardrailResult:
    """A triggered guardrail with its fault type and human-readable reason."""

    fault: GuardrailFault
    reason: str

    @property
    def is_session_fault(self) -> bool:
        """True when this fault requires turning the plug off and entering FAULTED."""
        return self.fault in (
            GuardrailFault.MAX_RUNTIME,
            GuardrailFault.MAX_ACTIVE_WH,
            GuardrailFault.SWITCH_COMMAND_FAILURE,
        )


class GuardrailEvaluator:
    """Stateful guardrail evaluator for one charge session.

    Lifecycle:
      - ``reset()`` when a new session begins (called by set_mode / morning reset).
      - ``on_charging_started(now)`` when TURN_ON is committed.
      - ``accumulate(power_w, idle_w, now)`` on every CHARGING tick with valid power.
      - ``on_turn_off_committed(now)`` when any TURN_OFF is committed.
      - ``check_*`` methods before or after each tick decision.
    """

    def __init__(self, config: Optional[GuardrailsConfig] = None) -> None:
        self._config = config or GuardrailsConfig()
        self._session_start: Optional[datetime] = None
        self._active_wh: float = 0.0
        self._relay_transitions: List[datetime] = []
        self._last_tick_time: Optional[datetime] = None
        self._pending_off_deadline: Optional[datetime] = None

    @property
    def active_wh(self) -> float:
        return self._active_wh

    def reset(self) -> None:
        """Reset all per-session state."""
        self._session_start = None
        self._active_wh = 0.0
        self._relay_transitions = []
        self._last_tick_time = None
        self._pending_off_deadline = None

    def on_charging_started(self, now: datetime) -> None:
        """Record session start when TURN_ON is committed."""
        self._session_start = now
        self._active_wh = 0.0
        self._relay_transitions = [now]
        self._last_tick_time = now

    def on_turn_off_committed(self, now: datetime) -> None:
        """Record a committed TURN_OFF and arm the command-confirmation deadline."""
        self._relay_transitions.append(now)
        self._pending_off_deadline = now + timedelta(
            seconds=self._config.command_confirm_seconds
        )

    def accumulate(self, power_w: float, idle_power_w: float, now: datetime) -> None:
        """Integrate active Wh for one CHARGING tick.

        Lazy-initialises session_start if on_charging_started was never called
        (e.g. after manual_override_on() which has no timestamp parameter).
        relay_transitions is intentionally left empty in that case so check_relay
        does not suppress the first toggle on the manual-override path.
        """
        if self._session_start is None:
            self._session_start = now
        if self._last_tick_time is not None:
            dt_s = (now - self._last_tick_time).total_seconds()
            if dt_s > 0:
                self._active_wh += max(power_w - idle_power_w, 0.0) * dt_s / 3600.0
        self._last_tick_time = now

    # ── Guardrail checks ──────────────────────────────────────────────────────

    def check_command_confirmation(
        self, plug_is_on: Optional[bool], now: datetime
    ) -> Optional[GuardrailResult]:
        """Return a fault if a previous TURN_OFF was not confirmed within the deadline.

        Clears the pending deadline when the plug reports off.
        """
        if self._pending_off_deadline is None:
            return None
        if plug_is_on is False:
            self._pending_off_deadline = None
            return None
        if plug_is_on is True and now >= self._pending_off_deadline:
            return GuardrailResult(
                fault=GuardrailFault.SWITCH_COMMAND_FAILURE,
                reason=(
                    f"plug still on {self._config.command_confirm_seconds:.0f} s "
                    "after TURN_OFF command"
                ),
            )
        return None

    def check_runtime(self, now: datetime) -> Optional[GuardrailResult]:
        """Fault if the charging session exceeds max_runtime_seconds."""
        if self._session_start is None:
            return None
        elapsed = (now - self._session_start).total_seconds()
        if elapsed >= self._config.max_runtime_seconds:
            return GuardrailResult(
                fault=GuardrailFault.MAX_RUNTIME,
                reason=(
                    f"max runtime {self._config.max_runtime_seconds:.0f} s exceeded "
                    f"({elapsed:.0f} s elapsed)"
                ),
            )
        return None

    def check_active_wh(self, max_wh: Optional[float]) -> Optional[GuardrailResult]:
        """Fault if accumulated active Wh exceeds *max_wh*.

        Pass the effective limit (profile-derived or config-set) from the caller.
        Returns None when *max_wh* is None (limit disabled).
        """
        if max_wh is None:
            return None
        if self._active_wh >= max_wh:
            return GuardrailResult(
                fault=GuardrailFault.MAX_ACTIVE_WH,
                reason=(
                    f"max active Wh {max_wh:.1f} exceeded "
                    f"({self._active_wh:.2f} Wh accumulated)"
                ),
            )
        return None

    def check_relay(self, is_toggle: bool, now: datetime) -> Optional[GuardrailResult]:
        """Suppress a proposed toggle if relay-chatter limits are exceeded.

        The initial TURN_ON (relay_transitions empty) is never suppressed.
        Subsequent toggles are checked against the cycle limit and minimum dwell.
        ``relay_cycle_limit`` is the maximum *total* transitions allowed
        (including the initial TURN_ON).
        """
        if not is_toggle or not self._relay_transitions:
            return None

        if len(self._relay_transitions) >= self._config.relay_cycle_limit:
            return GuardrailResult(
                fault=GuardrailFault.RELAY_LIMIT,
                reason=(
                    f"relay cycle limit {self._config.relay_cycle_limit} reached "
                    f"({len(self._relay_transitions)} transitions so far)"
                ),
            )

        elapsed = (now - self._relay_transitions[-1]).total_seconds()
        if elapsed < self._config.min_dwell_seconds:
            return GuardrailResult(
                fault=GuardrailFault.MIN_DWELL,
                reason=(
                    f"min dwell {self._config.min_dwell_seconds:.0f} s not elapsed "
                    f"({elapsed:.1f} s since last transition)"
                ),
            )
        return None
