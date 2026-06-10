"""Tests for CyclestewardCoordinator — pure Python, no HA imports required.

Scenarios A-J from bdd/ha-adapter/ha-entity-adapter-bdd.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, time as dtime
from pathlib import Path

import pytest

from cyclesteward.calibration import CalibrationProfile, ProfileState, SocAssumptions, WattageAnchor
from cyclesteward.guardrails import GuardrailFault, GuardrailsConfig
from cyclesteward.session_control import ChargeMode, SessionConfig, SessionState

from custom_components.cyclesteward.coordinator import CyclestewardCoordinator

# ── shared timestamps ────────────────────────────────────────────────────────

from datetime import timedelta

T0 = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def t(seconds: int) -> datetime:
    """Return T0 + seconds."""
    return T0 + timedelta(seconds=seconds)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def uncalibrated_profile() -> CalibrationProfile:
    return CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="test-meter",
    )


@pytest.fixture
def calibrated_profile() -> CalibrationProfile:
    """Profile with 65–95 W CC ramp; target at 80 % SoC = 95 W."""
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="test-meter",
    )
    p.watts_at_low = WattageAnchor(watts=65.0, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(watts=95.0, assumed_soc_label="cc_cv_transition")
    p.taper_floor_w = 15.0
    p.state = ProfileState.CALIBRATED
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    return p


@pytest.fixture
def basic_coordinator(uncalibrated_profile: CalibrationProfile) -> CyclestewardCoordinator:
    # morning_reset_time=23:00 so T0=08:00 ticks don't trigger morning reset
    config = SessionConfig(morning_reset_time=dtime(23, 0))
    return CyclestewardCoordinator(uncalibrated_profile, config=config)


@pytest.fixture
def calibrated_coordinator(calibrated_profile: CalibrationProfile) -> CyclestewardCoordinator:
    config = SessionConfig(target_soc_pct=80.0, morning_reset_time=dtime(23, 0))
    return CyclestewardCoordinator(calibrated_profile, config=config)


# ── Scenario A ───────────────────────────────────────────────────────────────


def test_A_mode_set_triggers_charging(basic_coordinator: CyclestewardCoordinator) -> None:
    """Scenario A: set_mode(CHARGE_TO_TARGET) then tick → TURN_ON + CHARGING."""
    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    result = basic_coordinator.tick(70.0, None, T0)

    assert result.action.value == "turn_on"
    assert result.state == SessionState.CHARGING
    assert basic_coordinator.session_state == SessionState.CHARGING


# ── Scenario B ───────────────────────────────────────────────────────────────


def test_B_mode_off_returns_idle(basic_coordinator: CyclestewardCoordinator) -> None:
    """Scenario B: set_mode(OFF) from CHARGING → IDLE."""
    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    basic_coordinator.tick(70.0, None, T0)  # → CHARGING

    basic_coordinator.set_mode(ChargeMode.OFF)

    assert basic_coordinator.charge_mode == ChargeMode.OFF
    assert basic_coordinator.session_state == SessionState.IDLE


# ── Scenario C ───────────────────────────────────────────────────────────────


def test_C_wattage_cutoff_done_latched_off(calibrated_coordinator: CyclestewardCoordinator) -> None:
    """Scenario C: wattage >= target (95 W) fires TURN_OFF + DONE_LATCHED_OFF."""
    calibrated_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

    r1 = calibrated_coordinator.tick(70.0, None, T0)
    assert r1.state == SessionState.CHARGING

    # 60 s later — well past min_dwell (30 s); wattage above 95 W threshold
    r2 = calibrated_coordinator.tick(96.0, None, t(60))

    assert r2.action.value == "turn_off"
    assert r2.state == SessionState.DONE_LATCHED_OFF
    assert calibrated_coordinator.session_state == SessionState.DONE_LATCHED_OFF


# ── Scenario D ───────────────────────────────────────────────────────────────


def test_D_session_state_reflects_controller(
    basic_coordinator: CyclestewardCoordinator,
) -> None:
    """Scenario D: session_state mirrors SessionController.state."""
    assert basic_coordinator.session_state == SessionState.IDLE

    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    basic_coordinator.tick(70.0, None, T0)

    assert basic_coordinator.session_state == SessionState.CHARGING


# ── Scenario E ───────────────────────────────────────────────────────────────


def test_E_charge_mode_reflects_controller(basic_coordinator: CyclestewardCoordinator) -> None:
    """Scenario E: charge_mode mirrors SessionController.mode."""
    assert basic_coordinator.charge_mode == ChargeMode.OFF

    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

    assert basic_coordinator.charge_mode == ChargeMode.CHARGE_TO_TARGET


# ── Scenario F ───────────────────────────────────────────────────────────────


def test_F_morning_reset_clears_mode(uncalibrated_profile: CalibrationProfile) -> None:
    """Scenario F: tick past morning reset time clears mode → OFF/IDLE."""
    config = SessionConfig(morning_reset_time=dtime(6, 0))
    coordinator = CyclestewardCoordinator(uncalibrated_profile, config=config)

    coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

    reset_time = datetime(2026, 1, 1, 6, 1, 0, tzinfo=timezone.utc)
    result = coordinator.tick(70.0, None, reset_time)

    assert result.reason == "morning reset: modes cleared"
    assert coordinator.charge_mode == ChargeMode.OFF
    assert coordinator.session_state == SessionState.IDLE


# ── Scenario G ───────────────────────────────────────────────────────────────


def test_G_guardrail_fault_propagates(uncalibrated_profile: CalibrationProfile) -> None:
    """Scenario G: max_runtime fault surfaces in TickResult.fault + FAULTED state."""
    config = SessionConfig(morning_reset_time=dtime(23, 0))
    guardrails = GuardrailsConfig(max_runtime_seconds=60.0)
    coordinator = CyclestewardCoordinator(
        uncalibrated_profile, config=config, guardrails_config=guardrails
    )

    coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    coordinator.tick(70.0, None, T0)  # → CHARGING, session starts at T0

    # 65 s later — exceeds max_runtime_seconds=60
    t_exceed = datetime(2026, 1, 1, 8, 1, 5, tzinfo=timezone.utc)
    result = coordinator.tick(70.0, None, t_exceed)

    assert result.fault == GuardrailFault.MAX_RUNTIME
    assert result.state == SessionState.FAULTED
    assert coordinator.session_state == SessionState.FAULTED


# ── Scenario H ───────────────────────────────────────────────────────────────


def test_H_soc_estimate_in_charging_tick(calibrated_coordinator: CyclestewardCoordinator) -> None:
    """Scenario H: second charging tick carries soc_estimate with uncertainty."""
    calibrated_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    calibrated_coordinator.tick(70.0, None, T0)  # first tick: TURN_ON, no SoC yet

    result = calibrated_coordinator.tick(75.0, None, t(10))

    assert result.soc_estimate is not None
    assert isinstance(result.soc_estimate.uncertainty_pct, float)
    assert isinstance(result.soc_estimate.low_confidence, bool)
    assert calibrated_coordinator.soc_estimate is not None
    assert calibrated_coordinator.soc_estimate is result.soc_estimate


# ── Scenario I ───────────────────────────────────────────────────────────────


def test_I_listener_notified_on_tick_and_mode_change(
    basic_coordinator: CyclestewardCoordinator,
) -> None:
    """Scenario I: listener called once per set_mode and once per tick."""
    calls: list[str] = []
    basic_coordinator.subscribe(lambda: calls.append("ping"))

    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    assert calls == ["ping"]

    basic_coordinator.tick(70.0, None, T0)
    assert calls == ["ping", "ping"]


# ── Scenario J ───────────────────────────────────────────────────────────────


def test_J_unsubscribe_stops_notifications(
    basic_coordinator: CyclestewardCoordinator,
) -> None:
    """Scenario J: unsubscribe callable stops further notifications."""
    calls: list[str] = []
    unsub = basic_coordinator.subscribe(lambda: calls.append("ping"))

    basic_coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)  # fires → 1 call
    unsub()
    basic_coordinator.tick(70.0, None, T0)  # should NOT fire

    assert calls == ["ping"]


# ── Anchor artifact ──────────────────────────────────────────────────────────

_TRACE_PATH = Path(__file__).resolve().parents[1] / "bdd/ha-adapter/ha-entity-adapter-trace.json"


def test_anchor_artifact_written(calibrated_profile: CalibrationProfile) -> None:
    """Generate trace JSON and verify expected state sequence is on disk."""
    config = SessionConfig(target_soc_pct=80.0, morning_reset_time=dtime(23, 0))
    coordinator = CyclestewardCoordinator(calibrated_profile, config=config)

    trace = []

    def _snap(label: str, result=None) -> None:
        entry = {
            "step": label,
            "charge_mode": coordinator.charge_mode.value,
            "session_state": coordinator.session_state.value,
        }
        if result is not None:
            entry["action"] = result.action.value
            entry["reason"] = result.reason
            if result.soc_estimate is not None:
                entry["soc_estimate"] = {
                    "estimated_soc_pct": result.soc_estimate.estimated_soc_pct,
                    "uncertainty_pct": result.soc_estimate.uncertainty_pct,
                    "low_confidence": result.soc_estimate.low_confidence,
                }
            if result.fault is not None:
                entry["fault"] = result.fault.value
        trace.append(entry)

    # Step 0: initial state
    _snap("initial")

    # Step 1: set mode
    coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    _snap("after set_mode(CHARGE_TO_TARGET)")

    # Step 2: first tick — TURN_ON
    r1 = coordinator.tick(70.0, None, T0)
    _snap("tick 1 — turn on", r1)

    # Step 3: mid-charge tick with SoC estimate
    r2 = coordinator.tick(78.0, None, t(30))
    _snap("tick 2 — charging (78 W)", r2)

    # Step 4: cutoff tick — wattage crosses 95 W
    r3 = coordinator.tick(96.0, None, t(60))
    _snap("tick 3 — cutoff (96 W)", r3)

    # Write to disk
    _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TRACE_PATH.write_text(json.dumps(trace, indent=2) + "\n")

    # Verify key expectations
    states = [e["session_state"] for e in trace]
    actions = [e.get("action") for e in trace if "action" in e]

    assert states[0] == "idle"
    assert states[2] == "charging"
    assert states[4] == "done_latched_off"
    assert "turn_on" in actions
    assert "turn_off" in actions

    # SoC estimate present on tick 2
    tick2 = trace[3]
    assert "soc_estimate" in tick2
    assert tick2["soc_estimate"]["uncertainty_pct"] <= 20.0


# ── Syntax check for HA entity files ─────────────────────────────────────────


def test_ha_entity_files_syntactically_valid() -> None:
    """All custom_components/cyclesteward/*.py files are valid Python syntax."""
    import ast
    import glob

    files = glob.glob("custom_components/cyclesteward/*.py")
    assert len(files) >= 7, f"expected at least 7 component files, found {len(files)}"
    for path in files:
        src = Path(path).read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"syntax error in {path}: {exc}")
