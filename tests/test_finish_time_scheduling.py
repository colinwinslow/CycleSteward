"""Tests for finish-time scheduling: PROBING state, computed_start_time, session_reason,
probe scheduling, logbook events, and overrun detection (ADR-0012 B–D).

Scenarios A–F from bdd/ha-adapter/finish-time-scheduling-bdd.md.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.guardrails import GuardrailsConfig
from cyclesteward.session_control import (
    ChargeMode,
    SessionConfig,
    SessionState,
)
from custom_components.cyclesteward.coordinator import CyclestewardCoordinator
from custom_components.cyclesteward.watcher import HASensorWatcher, _DEFAULT_MARGIN_S

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Use midnight UTC so morning-reset (06:00) never fires.
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _calibrated_profile(
    watts_at_low: float = 65.0,
    watts_at_transition: float = 130.0,
    duration_observations: Optional[list] = None,
) -> CalibrationProfile:
    from cyclesteward.calibration import FullObservation
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="test-meter",
    )
    p.state = ProfileState.CALIBRATED
    p.watts_at_low = WattageAnchor(watts=watts_at_low, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(
        watts=watts_at_transition, assumed_soc_label="cc_cv_transition"
    )
    p.taper_floor_w = 15.0
    p.active_full_wh = 400.0
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    if duration_observations:
        for elapsed_s in duration_observations:
            obs = FullObservation(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                active_wh=400.0,
                watts_at_low=watts_at_low,
                watts_at_transition=watts_at_transition,
                trusted=True,
                elapsed_seconds=elapsed_s,
            )
            p.full_observations.append(obs)
    return p


def _make_hass(plug_state: str = "off") -> SimpleNamespace:
    plug_mock = SimpleNamespace(state=plug_state)
    return SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: plug_mock),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=MagicMock()),
    )


def _make_watcher(
    profile=None,
    target_finish_time: Optional[datetime] = None,
    margin_s: float = _DEFAULT_MARGIN_S,
    max_probe_seconds: float = 300.0,
):
    if profile is None:
        profile = _calibrated_profile()
    config = SessionConfig(max_probe_seconds=max_probe_seconds)
    coordinator = CyclestewardCoordinator(profile, config=config)
    hass = _make_hass()
    watcher = HASensorWatcher(
        hass=hass,
        coordinator=coordinator,
        power_entity_id="sensor.plug_power",
        plug_entity_id="switch.plug",
        target_finish_time=target_finish_time,
        margin_s=margin_s,
    )
    return watcher, coordinator, hass


def run(coro):
    return asyncio.run(coro)


# ── Step 1 tests: PROBING state transitions ────────────────────────────────────


class TestProbingState:
    def test_probing_in_session_state_enum(self):
        assert SessionState.PROBING == "probing"

    def test_start_probe_transitions_waiting_to_probing(self):
        profile = _calibrated_profile()
        config = SessionConfig(scheduled_start=None)
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # Drive to WAITING_FOR_SCHEDULE; power must be non-None to pass the
        # "hold safely" guard in tick() and reach the schedule check.
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE
        # start_probe transitions to PROBING
        ok = coordinator.start_probe(T0)
        assert ok is True
        assert coordinator.session_state == SessionState.PROBING

    def test_start_probe_returns_false_if_not_waiting(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # IDLE, not WAITING_FOR_SCHEDULE
        assert coordinator.session_state == SessionState.IDLE
        ok = coordinator.start_probe(T0)
        assert ok is False
        assert coordinator.session_state == SessionState.IDLE

    def test_end_probe_transitions_probing_to_waiting(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        assert coordinator.session_state == SessionState.PROBING
        ok = coordinator.end_probe()
        assert ok is True
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

    def test_end_probe_returns_false_if_not_probing(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        ok = coordinator.end_probe()
        assert ok is False

    def test_probing_tick_returns_soc_estimate(self):
        """During PROBING, tick() returns a SoC estimate if power_w is available."""
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        # Tick with a CC-phase wattage
        result = coordinator.tick(90.0, None, t(30))
        assert result.state == SessionState.PROBING
        assert result.soc_estimate is not None

    def test_probing_tick_timeout_returns_to_waiting(self):
        """After max_probe_seconds, controller transitions PROBING → WAITING and issues TURN_OFF."""
        profile = _calibrated_profile()
        config = SessionConfig(max_probe_seconds=60.0)
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        # Tick past the probe timeout
        result = coordinator.tick(90.0, None, t(61))
        assert result.state == SessionState.WAITING_FOR_SCHEDULE
        from cyclesteward.session_control import SessionAction
        assert result.action == SessionAction.TURN_OFF
        assert "timeout" in result.reason.lower()

    def test_probing_accumulates_wh_for_energy_guardrail(self):
        """Wh consumed during PROBING counts toward the energy guardrail (ADR-0005 invariant 7).

        The end-to-end property: probe Wh must be *retained* when the real
        CHARGING session starts, not just accumulated during PROBING and then
        discarded (review finding F2).
        """
        profile = _calibrated_profile()
        profile.idle_power_w = 2.0
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        # Two probe ticks at 90W, 60s apart → active_wh accumulates
        coordinator.tick(90.0, None, t(30))
        coordinator.tick(90.0, None, t(60))
        probe_wh = coordinator.active_wh
        assert probe_wh > 0.0
        coordinator.end_probe()

        # Start time arrives → CHARGING.  Probe Wh must survive the transition.
        result = coordinator.tick(80.0, None, t(3600), computed_start_time=t(3600))
        assert result.state == SessionState.CHARGING
        assert coordinator.active_wh >= probe_wh

        # And further charging accumulation builds on top of the probe Wh.
        coordinator.tick(90.0, None, t(3660), computed_start_time=t(3600))
        assert coordinator.active_wh > probe_wh

    def test_probing_tick_with_no_power_stays_probing(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        result = coordinator.tick(None, None, t(30))
        assert result.state == SessionState.PROBING


class TestProbeRelayGuardrails:
    """Probe relay operations must go through the guardrail evaluator (review F3).

    ADR-0012 B: probes 'require the same guardrail path' as charge sessions —
    probe energizations count as relay cycles, and a probe TURN_OFF that the
    plug ignores must fault via command confirmation (guardrail D).
    """

    def test_probe_relay_transitions_counted(self):
        """start_probe and the timeout TURN_OFF each count as a relay transition."""
        profile = _calibrated_profile()
        config = SessionConfig(max_probe_seconds=60.0)
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        assert coordinator.relay_cycle_count == 0
        coordinator.start_probe(T0)
        assert coordinator.relay_cycle_count == 1
        coordinator.tick(90.0, None, t(61))  # timeout → TURN_OFF
        assert coordinator.relay_cycle_count == 2

    def test_probe_timeout_turn_off_arms_command_confirmation(self):
        """If the plug ignores the probe-timeout TURN_OFF, guardrail D faults."""
        from cyclesteward.guardrails import GuardrailFault

        profile = _calibrated_profile()
        config = SessionConfig(max_probe_seconds=60.0)
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        result = coordinator.tick(90.0, None, t(61))  # timeout → TURN_OFF
        assert result.state == SessionState.WAITING_FOR_SCHEDULE

        # Plug still reports on past the confirmation deadline (10 s default).
        result = coordinator.tick(
            90.0, None, t(75), plug_is_on=True, computed_start_time=t(3600)
        )
        assert result.state == SessionState.FAULTED
        assert result.fault == GuardrailFault.SWITCH_COMMAND_FAILURE

    def test_end_probe_with_now_arms_command_confirmation(self):
        """A successful probe's TURN_OFF (adapter-dispatched) is also confirmed."""
        from cyclesteward.guardrails import GuardrailFault

        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        coordinator.tick(90.0, None, t(30))
        coordinator.end_probe(t(40))

        result = coordinator.tick(
            90.0, None, t(55), plug_is_on=True, computed_start_time=t(3600)
        )
        assert result.state == SessionState.FAULTED
        assert result.fault == GuardrailFault.SWITCH_COMMAND_FAILURE

    def test_end_probe_confirmation_clears_when_plug_reports_off(self):
        """The armed probe TURN_OFF deadline clears normally when the plug obeys."""
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        coordinator.tick(90.0, None, t(30))
        coordinator.end_probe(t(40))

        result = coordinator.tick(
            5.0, None, t(55), plug_is_on=False, computed_start_time=t(3600)
        )
        assert result.state == SessionState.WAITING_FOR_SCHEDULE


# ── Step 2 tests: computed_start_time ──────────────────────────────────────────


class TestComputedStartTime:
    def test_waiting_when_before_computed_start(self):
        """When now < computed_start_time, stays WAITING_FOR_SCHEDULE."""
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        result = coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        assert result.state == SessionState.WAITING_FOR_SCHEDULE

    def test_charging_when_at_computed_start(self):
        """When now >= computed_start_time, transitions WAITING → CHARGING."""
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # First tick: wait
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        # Second tick: past start time
        result = coordinator.tick(80.0, None, t(3600), computed_start_time=t(3600))
        assert result.state == SessionState.CHARGING
        from cyclesteward.session_control import SessionAction
        assert result.action == SessionAction.TURN_ON

    def test_computed_start_takes_precedence_over_scheduled_start(self):
        """computed_start_time kwarg overrides SessionConfig.scheduled_start."""
        from datetime import time
        profile = _calibrated_profile()
        config = SessionConfig(scheduled_start=time(3, 0))  # 03:00 in config
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # T0 = midnight; scheduled_start=03:00 would block, but computed_start=T0
        # → should start immediately
        result = coordinator.tick(80.0, None, T0, computed_start_time=T0)
        assert result.state == SessionState.CHARGING

    def test_none_computed_start_falls_back_to_scheduled_start(self):
        """With computed_start_time=None, legacy scheduled_start is used."""
        from datetime import time
        profile = _calibrated_profile()
        config = SessionConfig(scheduled_start=time(3, 0))
        coordinator = CyclestewardCoordinator(profile, config=config)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # T0 = midnight; before scheduled_start 03:00 → WAITING
        result = coordinator.tick(80.0, None, T0, computed_start_time=None)
        assert result.state == SessionState.WAITING_FOR_SCHEDULE


# ── Step 3 tests: session_reason ──────────────────────────────────────────────


class TestSessionReason:
    def test_waiting_reason_is_human_readable(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        assert "Scheduled" in coordinator.session_reason
        assert coordinator.session_reason != ""

    def test_probing_reason_is_human_readable(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        result = coordinator.tick(90.0, None, t(10))
        assert "Probing" in result.reason

    def test_idle_reason_is_empty_or_mode_off(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        # Never had a tick; session_reason is empty
        assert coordinator.session_reason == ""

    def test_charging_reason_non_empty(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        result = coordinator.tick(80.0, None, T0)
        assert result.state == SessionState.CHARGING
        assert coordinator.session_reason != ""


# ── Step 4 tests: logbook event helper ────────────────────────────────────────


class TestLogbookEventHelper:
    def test_fire_event_calls_hass_bus(self):
        watcher, coordinator, hass = _make_watcher()
        watcher._fire_event("test_event", "test reason")
        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == "cyclesteward_event"
        data = call_args[0][1]
        assert data["event"] == "test_event"
        assert data["reason"] == "test reason"
        assert "timestamp" in data

    def test_fire_event_includes_extra_fields(self):
        watcher, coordinator, hass = _make_watcher()
        watcher._fire_event("probe_result", "done", {"soc_estimate_pct": 42.0})
        data = hass.bus.async_fire.call_args[0][1]
        assert data["soc_estimate_pct"] == pytest.approx(42.0)


# ── Step 5 tests: probe scheduling ────────────────────────────────────────────


class TestProbeScheduling:
    def test_pessimistic_start_time_with_no_observations(self):
        """No duration observations → 4 h default → pessimistic start = finish - 4h20m."""
        profile = _calibrated_profile()
        target = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)  # 07:00
        watcher, _, _ = _make_watcher(profile=profile, target_finish_time=target)
        # No observations: mean=4h, uncertainty=0.2*4h=48min, max=mean+2*48min=5h36min
        # pessimistic = 07:00 - 5h36min - 30min = 07:00 - 6h06min = 00:54
        pst = watcher._pessimistic_start_time()
        assert pst is not None
        # max_duration = 4h + 2*(0.8h) = 5.6h = 20160s; margin=1800s; total=21960s
        expected = target - timedelta(seconds=20160 + 1800)
        assert pst == expected

    def test_probe_time_is_pessimistic_start_minus_headroom(self):
        """probe_time = target - max_duration - margin - probe_headroom (10min)."""
        profile = _calibrated_profile()
        target = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
        watcher, _, _ = _make_watcher(profile=profile, target_finish_time=target)
        pst = watcher._pessimistic_start_time()
        pt = watcher._probe_time()
        assert pt is not None
        assert pt == pst - timedelta(seconds=600)  # probe_headroom = 10min

    def test_probe_fires_when_clock_reaches_probe_time(self):
        """At probe_time, watcher transitions coordinator to PROBING."""
        profile = _calibrated_profile()
        # target must be far enough ahead that pessimistic_start_time > T0.
        # No observations: max_duration = 5.6h, margin = 30min → total 6.1h.
        # Use 8h to ensure pessimistic_start = T0 + 8h - 6.1h = T0 + 1.9h > T0.
        target = t(8 * 3600)  # 8h from T0
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # Prime the controller into WAITING_FOR_SCHEDULE by setting computed_start_time
        # via set_target_finish_time (which initialises _computed_start_time).
        watcher.set_target_finish_time(target)
        # Drive to WAITING_FOR_SCHEDULE (power must be non-None to pass hold-safely guard).
        run(watcher._do_tick(80.0, T0))
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

        # At probe_time, probe should fire.
        pt = watcher._probe_time()
        assert pt is not None
        run(watcher._do_tick(80.0, pt))
        assert coordinator.session_state == SessionState.PROBING

        # probe_start logbook event fired
        fired_events = [
            call[0][1]["event"]
            for call in hass.bus.async_fire.call_args_list
        ]
        assert "probe_start" in fired_events

    def test_probe_refusal_never_energizes_plug(self):
        """If start_probe refuses (relay guardrail), the watcher must not turn
        the plug on — refusal falls back to the pessimistic start time (F3)."""
        profile = _calibrated_profile()
        target = t(8 * 3600)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        run(watcher._do_tick(80.0, T0))
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

        # Force a refusal regardless of guardrail state.
        coordinator.start_probe = lambda now: False

        pt = watcher._probe_time()
        run(watcher._do_tick(80.0, pt))
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE
        # No turn_on dispatched, no probe_start event; refusal event fired instead.
        assert hass.services.async_call.await_count == 0
        fired = [c[0][1]["event"] for c in hass.bus.async_fire.call_args_list]
        assert "probe_start" not in fired
        assert "probe_result" in fired

    def test_probe_fires_only_once_per_cycle(self):
        """_probe_fired flag prevents re-triggering on subsequent ticks."""
        profile = _calibrated_profile()
        target = t(8 * 3600)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        run(watcher._do_tick(80.0, T0))
        pt = watcher._probe_time()
        # Fire once at probe_time
        run(watcher._do_tick(80.0, pt))
        first_call_count = hass.bus.async_fire.call_count
        # Simulate end_probe so coordinator is no longer PROBING
        coordinator.end_probe()
        # Second tick past probe_time: no new probe_start event
        run(watcher._do_tick(80.0, pt + timedelta(seconds=10)))
        assert hass.bus.async_fire.call_count == first_call_count  # no new events for probe_start

    def test_probe_timeout_fires_probe_result_with_failure(self):
        """When probe times out, watcher fires probe_result with failure reason."""
        profile = _calibrated_profile()
        target = t(8 * 3600)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target, max_probe_seconds=10.0
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        run(watcher._do_tick(80.0, T0))

        # Trigger the probe
        pt = watcher._probe_time()
        run(watcher._do_tick(80.0, pt))
        assert coordinator.session_state == SessionState.PROBING

        # Run past probe timeout (power_w=None so no high-confidence reading, timeout fires)
        run(watcher._do_tick(None, pt + timedelta(seconds=11)))

        # Should be back to WAITING_FOR_SCHEDULE
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

        # computed_start_time must remain at the pessimistic default (Scenario B)
        assert watcher.computed_start_time == watcher._pessimistic_start_time()

        # probe_result event fired with failure info
        fired_events = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        probe_result_events = [e for e in fired_events if e["event"] == "probe_result"]
        assert len(probe_result_events) >= 1
        assert "timeout" in probe_result_events[-1]["reason"].lower()

    def test_no_target_finish_time_no_probe(self):
        """With no target_finish_time set, probe never fires."""
        profile = _calibrated_profile()
        watcher, coordinator, hass = _make_watcher(profile=profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # Tick many times — no probe should fire
        for i in range(5):
            run(watcher._do_tick(None, t(i * 600)))
        fired_events = [call[0][1]["event"] for call in hass.bus.async_fire.call_args_list]
        assert "probe_start" not in fired_events


# ── Step 6 tests: computed_start_time updated after successful probe ───────────


class TestComputedStartTimeUpdate:
    def test_successful_probe_updates_computed_start_time(self):
        """After a stable CC-phase reading, computed_start_time moves later."""
        profile = _calibrated_profile(watts_at_low=65.0, watts_at_transition=130.0)
        target = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pessimistic = watcher._computed_start_time

        # Drive to WAITING, fire probe (power must be non-None to reach schedule check)
        run(watcher._do_tick(80.0, T0))
        pt = watcher._probe_time()
        run(watcher._do_tick(80.0, pt))
        assert coordinator.session_state == SessionState.PROBING

        # Feed a stable, high-confidence CC wattage (90W → ~31% SoC, low_confidence=False)
        run(watcher._do_tick(90.0, pt + timedelta(seconds=10)))

        # Probe must have resolved: 90W is in CC range and calibrated → high confidence
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE, (
            f"Expected WAITING_FOR_SCHEDULE after stable reading, got {coordinator.session_state}"
        )
        refined = watcher.computed_start_time
        assert refined is not None
        # Refined start should be later than pessimistic (SoC ~31% → only ~69% remaining)
        assert refined >= pessimistic, (
            f"refined {refined} should be >= pessimistic {pessimistic}"
        )
        # probe_result event fired with soc info and uncertainty
        fired_events = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        probe_results = [e for e in fired_events if e["event"] == "probe_result"]
        assert len(probe_results) >= 1
        assert "soc_estimate_pct" in probe_results[-1]
        assert "uncertainty_pct" in probe_results[-1]


# ── Step 7 tests: overrun detection ───────────────────────────────────────────


class TestOverrunDetection:
    def test_overrun_event_fired_when_charging_past_finish_time(self):
        """If still CHARGING after target_finish_time, overrun event is fired."""
        profile = _calibrated_profile()
        target = t(300)  # 5 min from T0
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # Start charging (before target)
        run(watcher._do_tick(80.0, T0))
        assert coordinator.session_state == SessionState.CHARGING

        # Tick AFTER target_finish_time while still charging
        run(watcher._do_tick(80.0, t(310)))  # 310s > 300s target
        run(watcher._do_tick(80.0, t(320)))

        fired_events = [call[0][1]["event"] for call in hass.bus.async_fire.call_args_list]
        assert "overrun" in fired_events

    def test_no_overrun_event_when_no_target_finish_time(self):
        """Without a target_finish_time, overrun is never fired."""
        profile = _calibrated_profile()
        watcher, coordinator, hass = _make_watcher(profile=profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        run(watcher._do_tick(80.0, T0))
        run(watcher._do_tick(80.0, t(3600 * 24)))  # way in the future
        fired_events = [call[0][1]["event"] for call in hass.bus.async_fire.call_args_list]
        assert "overrun" not in fired_events

    def test_overrun_fires_only_once_per_session(self):
        """Overrun logbook event fires exactly once even with many ticks past target."""
        profile = _calibrated_profile()
        target = t(300)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        run(watcher._do_tick(80.0, T0))
        # Multiple ticks past target — overrun fires only once
        for i in range(5):
            run(watcher._do_tick(80.0, t(310 + i * 30)))
        fired_events = [call[0][1]["event"] for call in hass.bus.async_fire.call_args_list]
        assert fired_events.count("overrun") == 1

    def test_overrun_does_not_fault(self):
        """Overrun fires a logbook event only; charge session continues."""
        profile = _calibrated_profile()
        target = t(300)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        run(watcher._do_tick(80.0, T0))
        run(watcher._do_tick(80.0, t(310)))
        # Still CHARGING after overrun event
        assert coordinator.session_state == SessionState.CHARGING
        assert coordinator.active_fault is None


# ── Scenario D (BDD): session_reason always present on non-idle states ─────────


class TestScenarioDSessionReason:
    def test_waiting_reason_non_empty(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        result = coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        assert result.state == SessionState.WAITING_FOR_SCHEDULE
        assert result.reason != ""

    def test_probing_reason_non_empty(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(3600))
        coordinator.start_probe(T0)
        result = coordinator.tick(90.0, None, t(10))
        assert result.state == SessionState.PROBING
        assert result.reason != ""

    def test_charging_reason_non_empty(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        result = coordinator.tick(80.0, None, T0)
        assert result.state == SessionState.CHARGING
        assert result.reason != ""

    def test_done_latched_off_reason_non_empty(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # Charge to cutoff
        coordinator.tick(80.0, None, T0)
        result = coordinator.tick(130.0, None, t(60))  # at/above transition wattage
        assert result.state == SessionState.DONE_LATCHED_OFF
        assert coordinator.session_reason != ""

    def test_faulted_reason_non_empty(self):
        profile = _calibrated_profile()
        guardrails = GuardrailsConfig(max_runtime_seconds=60.0)
        coordinator = CyclestewardCoordinator(
            profile, guardrails_config=guardrails
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0)              # → CHARGING
        result = coordinator.tick(80.0, None, t(65))  # exceeds max_runtime_seconds → FAULTED
        assert result.state == SessionState.FAULTED
        assert coordinator.session_reason != ""

    def test_idle_reason_empty_before_first_tick(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        # No tick yet: session_reason is empty
        assert coordinator.session_reason == ""


# ── Scenario F (BDD): computed_start_time drives WAITING_FOR_SCHEDULE ─────────


class TestScenarioFWaitingTransition:
    def test_stays_waiting_before_computed_start(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        result = coordinator.tick(80.0, None, T0, computed_start_time=t(7200))
        assert result.state == SessionState.WAITING_FOR_SCHEDULE

    def test_transitions_to_charging_at_computed_start(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        coordinator.tick(80.0, None, T0, computed_start_time=t(7200))
        result = coordinator.tick(80.0, None, t(7200), computed_start_time=t(7200))
        assert result.state == SessionState.CHARGING
        from cyclesteward.session_control import SessionAction
        assert result.action == SessionAction.TURN_ON

    def test_session_start_event_fired_on_charging_transition(self):
        """session_start logbook event fires when WAITING → CHARGING.

        Use a coordinator without a watcher target (no probe) to isolate the
        WAITING→CHARGING transition and session_start event.  Probe scheduling
        is covered in TestProbeScheduling; mixing both here would require ending
        the probe before the start time.
        """
        profile = _calibrated_profile()
        target = t(8 * 3600)
        watcher, coordinator, hass = _make_watcher(
            profile=profile, target_finish_time=target
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # Do NOT call set_target_finish_time — we set computed_start_time directly
        # on the watcher to test just the session_start event path.
        watcher._computed_start_time = t(3600)
        watcher._probe_fired = True  # skip probe to isolate this test

        # Wait state
        run(watcher._do_tick(80.0, T0))
        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE
        # Advance to computed_start_time
        run(watcher._do_tick(80.0, t(3600)))
        assert coordinator.session_state == SessionState.CHARGING
        fired = [call[0][1]["event"] for call in hass.bus.async_fire.call_args_list]
        assert "session_start" in fired
