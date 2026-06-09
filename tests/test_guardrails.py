"""Guardrails slice A–G: automation fault detection.

Profile fixture: watts_at_low=70 W, watts_at_transition=100 W, active_full_wh=400 Wh.
  target_wattage(80 %) = 100.0 W
  max_active_wh (profile-derived) = 400.0 * 1.2 = 480.0 Wh

BDD scenarios:
  A - maximum runtime faults a stuck session
  B - maximum active Wh faults an impossible session
  C - relay chatter is prevented
  D - switch command failure is visible
  E - freeze lockout refuses to start charging when cold (session-control state machine)
  F - heat delays charging rather than blocking it (session-control state machine)
  G - missing or non-numeric readings default safely (session-control state machine)
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.guardrails import (
    GuardrailEvaluator,
    GuardrailFault,
    GuardrailsConfig,
)
from cyclesteward.session_control import (
    ChargeMode,
    SessionAction,
    SessionConfig,
    SessionController,
    SessionState,
    TemperatureConfig,
)

BDD_DIR = Path(__file__).resolve().parents[1] / "bdd" / "guardrails"

_T0 = datetime(2026, 1, 10, 4, 0, 0, tzinfo=timezone.utc)


def _t(**kwargs) -> datetime:
    return _T0 + timedelta(**kwargs)


def _calibrated_profile() -> CalibrationProfile:
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="sensor.plug_power",
    )
    p.watts_at_low = WattageAnchor(watts=70.0, assumed_soc_label="display_empty", confidence="high")
    p.watts_at_transition = WattageAnchor(
        watts=100.0, assumed_soc_label="cc_cv_transition", confidence="high"
    )
    p.taper_floor_w = 10.0
    p.active_full_wh = 400.0
    p.state = ProfileState.CALIBRATED
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    return p


# ── Scenario A: maximum runtime faults a stuck session ───────────────────────


def test_A_runtime_fault_fires_when_session_exceeds_limit():
    """A charging session past max_runtime_seconds → TURN_OFF + FAULTED."""
    config = GuardrailsConfig(max_runtime_seconds=60.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON; session clock starts

    r = ctrl.tick(80.0, None, _t(seconds=61))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.FAULTED
    assert r.fault == GuardrailFault.MAX_RUNTIME
    assert "max runtime" in r.reason.lower()


def test_A_no_fault_within_runtime_limit():
    config = GuardrailsConfig(max_runtime_seconds=3600.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)

    r = ctrl.tick(80.0, None, _t(minutes=30))
    assert r.state != SessionState.FAULTED
    assert r.fault is None


def test_A_faulted_session_does_not_resume_automatically():
    """After a runtime fault, subsequent ticks stay FAULTED and emit NONE."""
    config = GuardrailsConfig(max_runtime_seconds=60.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(80.0, None, _t(seconds=61))  # fault fires

    for i in range(3):
        r = ctrl.tick(80.0, None, _t(seconds=70 + i * 10))
        assert r.state == SessionState.FAULTED
        assert r.action == SessionAction.NONE


def test_A_event_log_records_runtime_fault():
    config = GuardrailsConfig(max_runtime_seconds=60.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(80.0, None, _t(seconds=61))

    assert any("max_runtime" in entry for entry in ctrl.event_log)


def test_A_evaluator_direct_runtime_check():
    """Unit-test GuardrailEvaluator.check_runtime in isolation."""
    ev = GuardrailEvaluator(GuardrailsConfig(max_runtime_seconds=100.0))
    ev.on_charging_started(_T0)
    assert ev.check_runtime(_T0 + timedelta(seconds=99)) is None
    result = ev.check_runtime(_T0 + timedelta(seconds=101))
    assert result is not None
    assert result.fault == GuardrailFault.MAX_RUNTIME
    assert result.is_session_fault


# ── Scenario B: maximum active Wh faults an impossible session ───────────────


def test_B_wh_fault_fires_when_accumulated_wh_exceeds_limit():
    """Wh > configured max_active_wh → TURN_OFF + FAULTED."""
    config = GuardrailsConfig(max_active_wh=1.0, max_runtime_seconds=999999)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON; idle_power_w=None → 0.0

    # At 80 W for 1 hour = 80 Wh >> 1 Wh limit.
    r = ctrl.tick(80.0, None, _t(hours=1))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.FAULTED
    assert r.fault == GuardrailFault.MAX_ACTIVE_WH
    assert "max active wh" in r.reason.lower()


def test_B_profile_derived_wh_limit_used_when_config_is_none():
    """active_full_wh * 1.2 = 480 Wh used when config.max_active_wh is None."""
    guardrails_cfg = GuardrailsConfig(max_active_wh=None, max_runtime_seconds=999999)
    # Push morning-reset to 23:00 so the 7-hour tick (11:00) doesn't trigger it.
    session_cfg = SessionConfig(morning_reset_time=time(23, 0))
    profile = _calibrated_profile()  # active_full_wh = 400.0
    ctrl = SessionController(profile, config=session_cfg, guardrails_config=guardrails_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)

    # 80 W for 7 hours = 560 Wh > 480 Wh.
    r = ctrl.tick(80.0, None, _t(hours=7))
    assert r.fault == GuardrailFault.MAX_ACTIVE_WH


def test_B_wh_guardrail_disabled_when_no_profile_no_config():
    """With no active_full_wh and no config.max_active_wh the Wh guardrail is off."""
    ev = GuardrailEvaluator(GuardrailsConfig(max_active_wh=None))
    ev.on_charging_started(_T0)
    ev.accumulate(1000.0, 0.0, _T0 + timedelta(hours=100))
    assert ev.check_active_wh(None) is None


def test_B_idle_power_subtracted_from_active_wh():
    """Only power above idle_power_w is counted towards active Wh."""
    profile = _calibrated_profile()
    profile.idle_power_w = 5.0  # 5 W standby
    config = GuardrailsConfig(max_active_wh=5.0, max_runtime_seconds=999999)
    ctrl = SessionController(profile, guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # active = 80 - 5 = 75 W

    # 75 W for 5 minutes = 75 * (300/3600) = 6.25 Wh > 5 Wh limit.
    r = ctrl.tick(80.0, None, _t(minutes=5))
    assert r.fault == GuardrailFault.MAX_ACTIVE_WH


def test_B_evaluator_no_wh_fault_below_limit():
    ev = GuardrailEvaluator(GuardrailsConfig(max_active_wh=100.0))
    ev.on_charging_started(_T0)
    ev.accumulate(80.0, 0.0, _T0 + timedelta(hours=1))  # 80 Wh
    assert ev.check_active_wh(100.0) is None


# ── Scenario C: relay chatter is prevented ───────────────────────────────────


def test_C_min_dwell_suppresses_rapid_cutoff():
    """TURN_OFF within min_dwell_seconds of TURN_ON is suppressed; session continues."""
    config = GuardrailsConfig(min_dwell_seconds=60.0, relay_cycle_limit=100)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON

    # Try to cut off at 30 s — min_dwell = 60 s not elapsed yet.
    r = ctrl.tick(101.0, None, _t(seconds=30))
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.CHARGING
    assert r.fault == GuardrailFault.MIN_DWELL
    assert "min dwell" in r.reason.lower()


def test_C_cutoff_allowed_after_dwell_period():
    """After min_dwell_seconds have passed, the cutoff fires normally."""
    config = GuardrailsConfig(min_dwell_seconds=30.0, relay_cycle_limit=100)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON

    r = ctrl.tick(101.0, None, _t(seconds=60))  # 60 s > 30 s dwell
    assert r.action == SessionAction.TURN_OFF
    assert r.fault is None


def test_C_relay_cycle_limit_suppresses_toggle():
    """Total transitions >= relay_cycle_limit → subsequent toggle suppressed."""
    # relay_cycle_limit=1: only the initial TURN_ON is allowed; the cutoff TURN_OFF is blocked.
    config = GuardrailsConfig(min_dwell_seconds=0.0, relay_cycle_limit=1)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON; transitions = [T0], len=1

    # With relay_cycle_limit=1, len(transitions)=1 >= 1 → suppressed.
    r = ctrl.tick(101.0, None, _t(seconds=60))
    assert r.action == SessionAction.NONE
    assert r.fault == GuardrailFault.RELAY_LIMIT
    assert "relay cycle limit" in r.reason.lower()


def test_C_initial_turn_on_never_suppressed():
    """The very first TURN_ON is never subject to relay chatter suppression."""
    config = GuardrailsConfig(min_dwell_seconds=999.0, relay_cycle_limit=0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, None, _T0)  # initial TURN_ON — relay_transitions is empty
    assert r.action == SessionAction.TURN_ON
    assert r.fault is None


def test_C_evaluator_check_relay_suppresses_below_dwell():
    ev = GuardrailEvaluator(GuardrailsConfig(min_dwell_seconds=60.0, relay_cycle_limit=100))
    ev.on_charging_started(_T0)
    result = ev.check_relay(True, _T0 + timedelta(seconds=30))
    assert result is not None
    assert result.fault == GuardrailFault.MIN_DWELL
    assert not result.is_session_fault


def test_C_evaluator_check_relay_empty_transitions_never_suppresses():
    ev = GuardrailEvaluator(GuardrailsConfig(min_dwell_seconds=999.0, relay_cycle_limit=0))
    # relay_transitions not initialised → empty
    assert ev.check_relay(True, _T0) is None


# ── Scenario D: switch command failure is visible ────────────────────────────


def test_D_command_failure_faults_when_plug_stays_on_past_deadline():
    """Plug still on after command_confirm_seconds → FAULTED + SWITCH_COMMAND_FAILURE."""
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)               # TURN_ON
    ctrl.tick(101.0, None, _t(minutes=2))    # cutoff → TURN_OFF → DONE_LATCHED_OFF

    # 11 s after TURN_OFF, plug is still on → past deadline.
    r = ctrl.tick(None, None, _t(minutes=2, seconds=11), plug_is_on=True)
    assert r.state == SessionState.FAULTED
    assert r.fault == GuardrailFault.SWITCH_COMMAND_FAILURE
    assert r.action == SessionAction.NONE


def test_D_no_fault_when_plug_confirms_off_before_deadline():
    """Plug turns off within the deadline → pending command cleared, no fault."""
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(101.0, None, _t(minutes=2))    # TURN_OFF → DONE_LATCHED_OFF

    # Plug confirms off at 5 s — within deadline.
    r = ctrl.tick(None, None, _t(minutes=2, seconds=5), plug_is_on=False)
    assert r.state == SessionState.DONE_LATCHED_OFF  # latch preserved
    assert r.fault is None

    # Subsequent tick with no plug state: confirmation already cleared, no fault.
    r2 = ctrl.tick(None, None, _t(minutes=2, seconds=20), plug_is_on=None)
    assert r2.state == SessionState.DONE_LATCHED_OFF
    assert r2.fault is None


def test_D_no_fault_before_deadline_even_if_plug_still_on():
    """A tick within the deadline does not fault even if plug is still on."""
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(101.0, None, _t(minutes=2))    # TURN_OFF → DONE_LATCHED_OFF

    # 3 s later, plug still on — within the 10 s deadline.
    r = ctrl.tick(None, None, _t(minutes=2, seconds=3), plug_is_on=True)
    assert r.state == SessionState.DONE_LATCHED_OFF
    assert r.fault is None


def test_D_command_fault_fires_from_done_latched_off_state():
    """Command confirmation runs before the DONE_LATCHED_OFF short-circuit."""
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(101.0, None, _t(minutes=2))   # DONE_LATCHED_OFF

    assert ctrl.state == SessionState.DONE_LATCHED_OFF
    r = ctrl.tick(None, None, _t(minutes=2, seconds=11), plug_is_on=True)
    assert r.state == SessionState.FAULTED  # overrides the latch


def test_D_no_pending_command_without_turn_off():
    """Without a prior TURN_OFF, plug_is_on has no effect."""
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON; pending_off_deadline is None

    # plug_is_on=True with no pending command → no fault.
    r = ctrl.tick(80.0, None, _t(seconds=30), plug_is_on=True)
    assert r.fault is None
    assert r.state == SessionState.CHARGING


def test_D_morning_reset_wins_over_pending_command_confirmation():
    """Morning reset fires before command confirmation; pending deadline is cleared.

    This is intentional: morning reset is a deliberate daily clean-up.  After a
    reset the session is cleared, so confirming the prior TURN_OFF is moot.
    """
    config = GuardrailsConfig(command_confirm_seconds=10.0)
    session_cfg = SessionConfig(morning_reset_time=time(6, 0))
    ctrl = SessionController(_calibrated_profile(), config=session_cfg, guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    # T0 = 04:00; cut off just before morning reset.
    ctrl.tick(80.0, None, _T0)
    morning_minus_5s = datetime(2026, 1, 10, 5, 59, 55, tzinfo=timezone.utc)
    ctrl.tick(101.0, None, morning_minus_5s)   # TURN_OFF → DONE_LATCHED_OFF, deadline = 06:00:05

    # First tick AT morning reset (06:00) — reset fires, clears pending command.
    morning = datetime(2026, 1, 10, 6, 0, 0, tzinfo=timezone.utc)
    r = ctrl.tick(None, None, morning, plug_is_on=True)
    assert "morning reset" in r.reason
    assert r.fault is None   # reset wins; no command-confirmation fault


# ── Scenario E: freeze lockout refuses to start charging when cold ────────────


def test_E_freeze_lockout_prevents_start():
    """Freeze lockout refuses to start charging below the threshold."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=5.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 2.0, _T0)  # 2 °C < 5 °C
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.IDLE
    assert "freeze" in r.reason.lower()


def test_E_freeze_lockout_with_sensor_offset():
    """Sensor offset is applied before the threshold comparison."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=5.0, sensor_offset_c=1.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 3.0, _T0)  # effective = 3 + 1 = 4 °C < 5 °C
    assert r.state == SessionState.IDLE
    assert "4.0" in r.reason


def test_E_freeze_lockout_allows_start_above_threshold():
    """No lockout when temperature is above freeze_threshold_c."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=5.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 10.0, _T0)  # 10 °C > 5 °C
    assert r.action == SessionAction.TURN_ON


# ── Scenario F: heat delays charging rather than blocking it ─────────────────


def test_F_heat_delay_enters_non_fault_waiting_state():
    """Temperature above heat-delay threshold enters HEAT_DELAY, not FAULTED."""
    temp_cfg = TemperatureConfig(heat_delay_threshold_c=30.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 35.0, _T0)
    assert r.state == SessionState.HEAT_DELAY
    assert r.action == SessionAction.NONE
    assert r.fault is None


def test_F_heat_delay_retries_after_cooling():
    """After cooling below threshold, HEAT_DELAY exits and charging begins."""
    temp_cfg = TemperatureConfig(heat_delay_threshold_c=30.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    ctrl.tick(80.0, 35.0, _T0)  # → HEAT_DELAY
    r = ctrl.tick(80.0, 25.0, _t(hours=1))
    assert r.action == SessionAction.TURN_ON
    assert r.state == SessionState.CHARGING


def test_F_heat_delay_deadline_skips_session_with_notification():
    """Past deadline without cooling, session is skipped and mode resets to off."""
    temp_cfg = TemperatureConfig(
        heat_delay_threshold_c=30.0,
        heat_delay_deadline_seconds=600.0,
    )
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    ctrl.tick(80.0, 35.0, _T0)
    r = ctrl.tick(80.0, 35.0, _t(minutes=11))
    assert "deadline exceeded" in r.reason.lower()
    assert ctrl.mode == ChargeMode.OFF


# ── Scenario G: missing/non-numeric readings default safely ──────────────────


def test_G_none_power_holds_state_without_cutoff():
    """power_w=None holds current state; no cutoff misfire."""
    ctrl = SessionController(_calibrated_profile())
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # start charging

    r = ctrl.tick(None, None, _t(minutes=1))
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.CHARGING
    assert "unavailable" in r.reason.lower()
    assert r.fault is None


def test_G_none_power_does_not_accumulate_wh():
    """Missing power does not increment active Wh."""
    config = GuardrailsConfig(max_active_wh=0.01, max_runtime_seconds=999999)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)

    # Even after a long time with None power, no Wh should accumulate.
    for i in range(5):
        r = ctrl.tick(None, None, _t(hours=i + 1))
        assert r.fault != GuardrailFault.MAX_ACTIVE_WH


def test_G_none_temperature_proceeds_ungated():
    """temperature_c=None disables gating; charging starts regardless."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=25.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, None, _T0)  # no temperature reading
    assert r.action == SessionAction.TURN_ON


# ── Anchor artifact: guardrail decision trace ─────────────────────────────────


def test_generate_guardrails_fault_trace():
    """Produce the guardrails anchor artifact: a JSON trace showing a runtime fault.

    The trace shows: IDLE → CHARGING (normal) → FAULTED (runtime guardrail A).
    Saved to bdd/guardrails/guardrails-trace.json.
    """
    config = GuardrailsConfig(max_runtime_seconds=300.0)  # 5-minute limit
    profile = _calibrated_profile()
    ctrl = SessionController(profile, guardrails_config=config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    samples = [
        (0, 70.0),
        (60, 75.0),
        (120, 80.0),
        (180, 82.0),
        (240, 84.0),
        (301, 84.0),   # 1 s past 300 s limit → runtime fault
        (320, 84.0),   # latch check: stays FAULTED
    ]

    events = []
    for seconds, power in samples:
        now = _T0 + timedelta(seconds=seconds)
        result = ctrl.tick(power, None, now)
        events.append(
            {
                "timestamp": now.isoformat(),
                "power_w": power,
                **result.to_dict(),
            }
        )

    trace = {
        "scenario": "guardrail-A: IDLE → CHARGING → FAULTED (max-runtime)",
        "config": {
            "max_runtime_seconds": config.max_runtime_seconds,
        },
        "profile": {
            "watts_at_low": profile.watts_at_low.watts,
            "watts_at_transition": profile.watts_at_transition.watts,
            "active_full_wh": profile.active_full_wh,
        },
        "events": events,
    }

    BDD_DIR.mkdir(parents=True, exist_ok=True)
    out = BDD_DIR / "guardrails-trace.json"
    out.write_text(json.dumps(trace, indent=2) + "\n")

    # Verify artifact content.
    data = json.loads(out.read_text())
    states = [e["state"] for e in data["events"]]
    faults = [e.get("fault") for e in data["events"]]

    assert "charging" in states
    assert "faulted" in states
    assert "max_runtime" in faults

    fault_event = next(e for e in data["events"] if e.get("fault") == "max_runtime")
    assert fault_event["action"] == "turn_off"

    latch_event = data["events"][-1]
    assert latch_event["state"] == "faulted"
    assert latch_event["action"] == "none"
