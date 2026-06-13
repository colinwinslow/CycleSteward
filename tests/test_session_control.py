"""Session-control state machine — BDD scenarios A–H.

Profile fixture: watts_at_low=70 W (0 % SoC), watts_at_transition=100 W (80 % SoC).
  target_wattage(50 %) = 70 + (50/80)*30 = 88.75 W
  target_wattage(80 %) = 100.0 W
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.session_control import (
    ChargeMode,
    SessionAction,
    SessionConfig,
    SessionController,
    SessionState,
    TemperatureConfig,
)

BDD_DIR = Path(__file__).resolve().parents[1] / "bdd" / "session-control"

# Fixed base timestamp: 2026-01-10 04:00 UTC — before the 06:00 morning reset
_T0 = datetime(2026, 1, 10, 4, 0, 0, tzinfo=timezone.utc)


def _t(hours: float = 0, minutes: float = 0, seconds: float = 0) -> datetime:
    """Offset from _T0 by the given hours/minutes/seconds."""
    from datetime import timedelta

    return _T0 + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _calibrated_profile(taper_floor_w: float = 10.0) -> CalibrationProfile:
    """Minimal calibrated profile for state-machine tests.

    watts_at_low=70 W  → assumed 0 % SoC
    watts_at_transition=100 W → assumed 80 % SoC
    taper_floor_w=10 W
    """
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="sensor.plug_power",
    )
    p.watts_at_low = WattageAnchor(
        watts=70.0, assumed_soc_label="display_empty", confidence="high"
    )
    p.watts_at_transition = WattageAnchor(
        watts=100.0, assumed_soc_label="cc_cv_transition", confidence="high"
    )
    p.taper_floor_w = taper_floor_w
    p.active_full_wh = 400.0
    p.state = ProfileState.CALIBRATED
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    return p


def _partial_profile() -> CalibrationProfile:
    """Profile in CALIBRATING state — used for Scenario G (low-confidence SoC)."""
    p = _calibrated_profile()
    p.state = ProfileState.CALIBRATING
    return p


# ── Scenario A: cut off when wattage first crosses the target threshold ───────


def test_scenario_A_initial_tick_starts_charging():
    """First tick after set_mode transitions IDLE → CHARGING and issues TURN_ON."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    r = ctrl.tick(80.0, None, _T0)
    assert r.action == SessionAction.TURN_ON
    assert r.state == SessionState.CHARGING


def test_scenario_A_below_target_keeps_charging():
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # start charging
    r = ctrl.tick(85.0, None, _t(minutes=1))
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.CHARGING


def test_scenario_A_cutoff_fires_on_first_crossing():
    """Wattage >= 88.75 W (50 % target) triggers TURN_OFF and DONE_LATCHED_OFF."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON
    ctrl.tick(85.0, None, _t(minutes=1))  # below target
    r = ctrl.tick(89.0, None, _t(minutes=2))  # first crossing
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.DONE_LATCHED_OFF
    assert "cutoff" in r.reason.lower()
    # :.1f formats 88.75 → "88.8" (rounds to nearest tenth)
    assert "88.8" in r.reason


def test_scenario_A_no_double_gate():
    """Cutoff fires on the first crossing with no separate condition gate."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    # Exactly at threshold
    r = ctrl.tick(88.75, None, _t(minutes=1))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.DONE_LATCHED_OFF


# ── Scenario B: latch holds after cutoff ─────────────────────────────────────


def test_scenario_B_latch_persists_across_ticks():
    """After DONE_LATCHED_OFF, subsequent ticks never issue TURN_ON."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(89.0, None, _t(minutes=1))  # cutoff
    # Stay within the same hour to avoid crossing the 06:00 morning reset.
    for i in range(5):
        r = ctrl.tick(40.0, None, _t(minutes=i + 2))
        assert r.action == SessionAction.NONE
        assert r.state == SessionState.DONE_LATCHED_OFF


def test_scenario_B_new_set_mode_unlocks_latch():
    """Setting a new mode after latch starts a fresh session."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)
    ctrl.tick(89.0, None, _t(minutes=1))
    assert ctrl.state == SessionState.DONE_LATCHED_OFF
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    assert ctrl.state == SessionState.IDLE
    # Stay well before 06:00 morning reset.
    r = ctrl.tick(80.0, None, _t(minutes=10))
    assert r.action == SessionAction.TURN_ON


# ── Scenario C: scheduled charging starts at configured time ─────────────────


def test_scenario_C_waits_before_scheduled_start():
    """Ticks before the scheduled time stay in WAITING_FOR_SCHEDULE."""
    config = SessionConfig(
        target_soc_pct=50.0,
        scheduled_start=time(22, 0),  # 10 pm
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    # _T0 is 2 pm — before 10 pm
    r = ctrl.tick(80.0, None, _T0)
    assert r.state == SessionState.WAITING_FOR_SCHEDULE
    assert r.action == SessionAction.NONE


def test_scenario_C_starts_at_scheduled_time():
    """A tick at or after the scheduled time begins charging."""
    config = SessionConfig(
        target_soc_pct=50.0,
        scheduled_start=time(4, 0),  # same as _T0 time (04:00)
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    # _T0 is exactly 14:00 — at the scheduled start
    r = ctrl.tick(80.0, None, _T0)
    assert r.action == SessionAction.TURN_ON
    assert r.state == SessionState.CHARGING


def test_scenario_C_transitions_from_waiting_to_charging():
    """After waiting, the first tick past the scheduled time transitions to CHARGING."""
    config = SessionConfig(
        target_soc_pct=50.0,
        scheduled_start=time(4, 1),  # 1 minute after _T0 (04:01)
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r1 = ctrl.tick(80.0, None, _T0)  # 14:00 — before 14:01
    assert r1.state == SessionState.WAITING_FOR_SCHEDULE

    r2 = ctrl.tick(80.0, None, _t(minutes=2))  # 14:02 — past 14:01
    assert r2.action == SessionAction.TURN_ON
    assert r2.state == SessionState.CHARGING


# ── Scenario D: modes off by default and reset each morning ──────────────────


def test_scenario_D_morning_reset_clears_mode():
    """Morning reset at 06:00 clears the mode and enters IDLE."""
    config = SessionConfig(
        target_soc_pct=50.0,
        morning_reset_time=time(6, 0),
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    # Tick at 5:59 the following day — mode still active
    next_day_0559 = datetime(2026, 1, 11, 5, 59, 0, tzinfo=timezone.utc)
    r = ctrl.tick(80.0, None, next_day_0559)
    assert ctrl.mode == ChargeMode.CHARGE_TO_TARGET

    # Tick at 6:00 — morning reset fires
    next_day_0600 = datetime(2026, 1, 11, 6, 0, 0, tzinfo=timezone.utc)
    r = ctrl.tick(80.0, None, next_day_0600)
    assert "morning reset" in r.reason
    assert ctrl.mode == ChargeMode.OFF
    assert r.state == SessionState.IDLE


def test_scenario_D_after_reset_no_charging():
    """After morning reset, subsequent ticks do not start charging."""
    config = SessionConfig(morning_reset_time=time(6, 0))
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    # Arming tick before the boundary (a fresh controller's first tick never
    # fires the reset — review finding F4).
    ctrl.tick(80.0, None, datetime(2026, 1, 11, 5, 55, 0, tzinfo=timezone.utc))

    morning = datetime(2026, 1, 11, 6, 0, 0, tzinfo=timezone.utc)
    ctrl.tick(80.0, None, morning)  # fires reset
    r = ctrl.tick(80.0, None, morning.replace(minute=5))
    assert r.action == SessionAction.NONE
    assert ctrl.mode == ChargeMode.OFF


def test_scenario_D_morning_reset_fires_once_per_day():
    """Morning reset fires once; subsequent ticks that day do not re-fire it."""
    config = SessionConfig(morning_reset_time=time(6, 0))
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    # Arming tick before the boundary (review finding F4).
    ctrl.tick(80.0, None, datetime(2026, 1, 11, 5, 55, 0, tzinfo=timezone.utc))

    morning = datetime(2026, 1, 11, 6, 0, 0, tzinfo=timezone.utc)
    r1 = ctrl.tick(80.0, None, morning)
    assert "morning reset" in r1.reason

    # Re-set mode; tick again same morning — should NOT re-fire reset
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    r2 = ctrl.tick(80.0, None, morning.replace(minute=10))
    assert "morning reset" not in r2.reason
    assert r2.action == SessionAction.TURN_ON


def test_scenario_D_fresh_controller_first_tick_does_not_clear_mode():
    """A fresh controller's first tick past the reset time must NOT fire the reset.

    Regression for review finding F4: after an HA restart in the evening, the
    first tick used to clear a just-set mode because _last_morning_reset was
    None and 'now' was already past today's reset time.
    """
    config = SessionConfig(morning_reset_time=time(6, 0))
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    evening = datetime(2026, 1, 10, 22, 0, 0, tzinfo=timezone.utc)
    r = ctrl.tick(80.0, None, evening)
    assert "morning reset" not in r.reason
    assert ctrl.mode == ChargeMode.CHARGE_TO_TARGET


def test_scenario_D_fresh_controller_still_resets_next_morning():
    """The first-tick arming must not suppress the genuine next-morning reset."""
    config = SessionConfig(morning_reset_time=time(6, 0))
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    evening = datetime(2026, 1, 10, 22, 0, 0, tzinfo=timezone.utc)
    ctrl.tick(80.0, None, evening)

    next_morning = datetime(2026, 1, 11, 6, 0, 0, tzinfo=timezone.utc)
    r = ctrl.tick(80.0, None, next_morning)
    assert "morning reset" in r.reason
    assert ctrl.mode == ChargeMode.OFF


# ── Scenario E: manual override still honors the cutoff ──────────────────────


def test_scenario_E_manual_override_bypasses_schedule():
    """manual_override_on() forces CHARGING state, bypassing the scheduled start."""
    config = SessionConfig(
        target_soc_pct=50.0,
        scheduled_start=time(23, 0),  # 11 pm — well after _T0 (2 pm)
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, None, _T0)
    assert r.state == SessionState.WAITING_FOR_SCHEDULE

    ctrl.manual_override_on()
    assert ctrl.state == SessionState.CHARGING


def test_scenario_E_manual_override_cutoff_fires():
    """Cutoff still fires on the manual-override path when wattage crosses target."""
    config = SessionConfig(
        target_soc_pct=50.0,
        scheduled_start=time(23, 0),
    )
    ctrl = SessionController(_calibrated_profile(), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # → WAITING_FOR_SCHEDULE
    ctrl.manual_override_on()  # → CHARGING

    r = ctrl.tick(89.0, None, _t(minutes=5))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.DONE_LATCHED_OFF


# ── Scenario F: "Charge to full" — best-effort taper detection ───────────────


def test_scenario_F_charges_until_taper_floor():
    """CHARGE_TO_FULL waits for wattage to stay below taper_floor for configured duration."""
    config = SessionConfig(taper_below_floor_seconds=60.0)
    ctrl = SessionController(_calibrated_profile(taper_floor_w=12.0), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_FULL)
    ctrl.tick(90.0, None, _T0)  # TURN_ON

    # Still above taper floor
    r = ctrl.tick(50.0, None, _t(minutes=1))
    assert r.state == SessionState.CHARGING

    # Below taper floor but duration not met (only 30 s)
    r = ctrl.tick(8.0, None, _t(minutes=2))
    assert r.state == SessionState.CHARGING
    assert r.action == SessionAction.NONE

    r = ctrl.tick(8.0, None, _t(minutes=2, seconds=30))
    assert r.state == SessionState.CHARGING  # not yet 60 s

    # Duration met (>60 s below floor)
    r = ctrl.tick(8.0, None, _t(minutes=3, seconds=1))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.DONE_LATCHED_OFF
    assert "best-effort" in r.reason


def test_scenario_F_taper_timer_resets_when_power_rises():
    """If power climbs back above the floor, the taper timer resets."""
    config = SessionConfig(taper_below_floor_seconds=60.0)
    ctrl = SessionController(_calibrated_profile(taper_floor_w=12.0), config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_FULL)
    ctrl.tick(90.0, None, _T0)  # TURN_ON

    ctrl.tick(8.0, None, _t(minutes=2))  # starts taper timer
    ctrl.tick(20.0, None, _t(minutes=2, seconds=30))  # rises: timer cleared
    ctrl.tick(8.0, None, _t(minutes=3))  # back below: timer restarts

    # Only 30 s below floor since the timer reset — should not cut off yet
    r = ctrl.tick(8.0, None, _t(minutes=3, seconds=30))
    assert r.state == SessionState.CHARGING


# ── Scenario G: uncertain SoC estimate is surfaced ───────────────────────────


def test_scenario_G_low_confidence_when_calibrating():
    """SoC estimate carries low_confidence when the profile is not fully calibrated."""
    ctrl = SessionController(_partial_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(70.0, None, _T0)  # TURN_ON
    r = ctrl.tick(80.0, None, _t(minutes=1))
    assert r.soc_estimate is not None
    assert r.soc_estimate.low_confidence is True
    assert r.soc_estimate.uncertainty_pct > 10.0


def test_scenario_G_high_confidence_when_calibrated():
    """SoC estimate has high confidence (low_confidence=False) for a calibrated profile."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(70.0, None, _T0)
    r = ctrl.tick(80.0, None, _t(minutes=1))
    assert r.soc_estimate is not None
    assert r.soc_estimate.low_confidence is False
    assert r.soc_estimate.uncertainty_pct <= 10.0


def test_scenario_G_soc_estimate_formula():
    """SoC = 0 + (80-70)/(100-70) * 80 = 26.7 % at 80 W with 50 % target profile."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    est = ctrl.estimate_soc(80.0)
    assert est is not None
    assert abs(est.estimated_soc_pct - 26.7) < 0.2


def test_scenario_G_above_transition_flags_low_confidence():
    """Wattage at or above the transition anchor marks the estimate as low-confidence."""
    ctrl = SessionController(_calibrated_profile(), SessionConfig(target_soc_pct=50.0))
    est = ctrl.estimate_soc(105.0)
    assert est is not None
    assert est.low_confidence is True
    assert "transition" in est.note.lower()


def test_scenario_G_uncalibrated_profile_flags_low_confidence():
    """An uncalibrated profile returns a low-confidence placeholder estimate."""
    bare = CalibrationProfile(
        charger_label="x", battery_label="y", meter_id="z"
    )
    ctrl = SessionController(bare)
    est = ctrl.estimate_soc(80.0)
    assert est is not None
    assert est.low_confidence is True


# ── Scenario H: temperature gate prevents starting ───────────────────────────


def test_scenario_H_freeze_lockout_prevents_start():
    """Freeze lockout refuses to start charging below the threshold."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=5.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 2.0, _T0)  # 2 °C < 5 °C freeze threshold
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.IDLE
    assert "freeze" in r.reason.lower()


def test_scenario_H_freeze_lockout_records_reason():
    """Freeze lockout reason includes the effective temperature."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=5.0, sensor_offset_c=1.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 3.0, _T0)  # effective = 3 + 1 = 4 °C < 5 °C
    assert "4.0" in r.reason
    assert "5.0" in r.reason


def test_scenario_H_heat_delay_enters_waiting_state():
    """Temperature above heat-delay threshold enters HEAT_DELAY, not a fault."""
    temp_cfg = TemperatureConfig(heat_delay_threshold_c=30.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, 35.0, _T0)  # 35 °C > 30 °C
    assert r.state == SessionState.HEAT_DELAY
    assert r.action == SessionAction.NONE
    assert "heat delay" in r.reason.lower()


def test_scenario_H_heat_delay_retries_when_cooled():
    """After cooling below threshold, HEAT_DELAY exits and charging begins."""
    temp_cfg = TemperatureConfig(heat_delay_threshold_c=30.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    ctrl.tick(80.0, 35.0, _T0)  # → HEAT_DELAY
    r = ctrl.tick(80.0, 25.0, _t(hours=1))  # cooled → exits HEAT_DELAY
    assert r.action == SessionAction.TURN_ON
    assert r.state == SessionState.CHARGING


def test_scenario_H_heat_delay_deadline_skips_session():
    """Past the heat-delay deadline, the session is skipped and mode resets to off."""
    temp_cfg = TemperatureConfig(
        heat_delay_threshold_c=30.0,
        heat_delay_deadline_seconds=600.0,  # 10-minute deadline
    )
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    ctrl.tick(80.0, 35.0, _T0)  # → HEAT_DELAY
    # Still hot past the deadline
    r = ctrl.tick(80.0, 35.0, _t(minutes=11))
    assert "deadline exceeded" in r.reason.lower()
    assert ctrl.mode == ChargeMode.OFF


def test_scenario_H_no_sensor_proceeds_ungated():
    """With temperature_c=None (no sensor), temperature gating is disabled."""
    temp_cfg = TemperatureConfig(freeze_threshold_c=25.0)  # would block if sensor present
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r = ctrl.tick(80.0, None, _T0)  # no temperature reading
    assert r.action == SessionAction.TURN_ON  # gating skipped


# ── Missing/non-numeric readings default safely ───────────────────────────────


def test_missing_power_holds_state():
    """A None power reading returns NONE action and holds the current state."""
    ctrl = SessionController(_calibrated_profile())
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # start charging

    r = ctrl.tick(None, None, _t(minutes=1))
    assert r.action == SessionAction.NONE
    assert r.state == SessionState.CHARGING
    assert "unavailable" in r.reason.lower()


# ── Temperature compensation ─────────────────────────────────────────────────


def test_temp_compensation_shifts_target_up_when_cold():
    """When cold, the adjusted target wattage is higher, compensating for elevated readings."""
    temp_cfg = TemperatureConfig(
        temp_coeff_w_per_c=0.5,  # 0.5 W/°C
        baseline_temp_c=20.0,
    )
    config = SessionConfig(target_soc_pct=50.0)
    ctrl = SessionController(_calibrated_profile(), config, temp_cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, 10.0, _T0)  # start charging (10 °C, cold)

    # base target = 88.75 W; compensation = 0.5*(10-20) = -5 W → adjusted = 83.75 W
    # wattage 84.0 W should trigger cutoff at cold temperature
    r = ctrl.tick(84.0, 10.0, _t(minutes=1))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.DONE_LATCHED_OFF


def test_temp_compensation_adds_note_to_soc_estimate():
    """SoC estimate note mentions temperature compensation when coeff != 0."""
    temp_cfg = TemperatureConfig(temp_coeff_w_per_c=0.5, baseline_temp_c=20.0)
    ctrl = SessionController(_calibrated_profile(), temp_config=temp_cfg)
    est = ctrl.estimate_soc(80.0, temperature_c=15.0)
    assert est is not None
    assert "temperature-compensated" in est.note


# ── Anchor artifact: state-machine trace (Scenario A) ────────────────────────


def test_generate_charge_to_target_trace():
    """Produce the session-control anchor artifact: a JSON state-machine trace.

    The trace demonstrates a full IDLE → CHARGING → DONE_LATCHED_OFF path
    and is saved to bdd/session-control/session-control-trace.json.
    """
    profile = _calibrated_profile()
    # target_wattage(50%) = 88.75 W
    config = SessionConfig(target_soc_pct=50.0)
    ctrl = SessionController(profile, config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)

    samples = [
        # (minutes_offset, power_w)
        (0, 70.0),
        (5, 75.0),
        (10, 80.0),
        (15, 85.0),
        (20, 88.0),
        (25, 89.0),  # first crossing
        (30, 89.0),  # latch check
    ]

    events = []
    for minutes, power in samples:
        now = _t(minutes=minutes)
        result = ctrl.tick(power, None, now)
        events.append(
            {
                "timestamp": now.isoformat(),
                "power_w": power,
                **result.to_dict(),
            }
        )
        if result.state == SessionState.DONE_LATCHED_OFF and result.action == SessionAction.TURN_OFF:
            break  # stop collecting after first cutoff

    # Add one latch-verification tick
    r_latch = ctrl.tick(40.0, None, _t(hours=1))
    events.append(
        {
            "timestamp": _t(hours=1).isoformat(),
            "power_w": 40.0,
            **r_latch.to_dict(),
        }
    )

    target_w = profile.target_wattage(50.0)
    trace = {
        "scenario": "charge-to-target: IDLE → CHARGING → DONE_LATCHED_OFF",
        "profile": {
            "watts_at_low": profile.watts_at_low.watts,
            "watts_at_transition": profile.watts_at_transition.watts,
            "assumed_soc_at_low_pct": profile.assumptions.soc_at_low_pct,
            "assumed_soc_at_transition_pct": profile.assumptions.soc_at_transition_pct,
            "target_soc_pct": config.target_soc_pct,
            "target_wattage_w": round(target_w, 3) if target_w else None,
        },
        "events": events,
    }

    # Write the artifact to the BDD directory.
    out = BDD_DIR / "session-control-trace.json"
    out.write_text(json.dumps(trace, indent=2) + "\n")

    # Verify the artifact was produced and contains the expected transitions.
    trace_data = json.loads(out.read_text())
    states = [e["state"] for e in trace_data["events"]]
    assert "charging" in states
    assert "done_latched_off" in states
    # Cutoff event references the target wattage
    cutoff_event = next(e for e in trace_data["events"] if e["state"] == "done_latched_off")
    assert cutoff_event["action"] == "turn_off"
    # Latch holds after cutoff
    latch_event = trace_data["events"][-1]
    assert latch_event["state"] == "done_latched_off"
    assert latch_event["action"] == "none"
