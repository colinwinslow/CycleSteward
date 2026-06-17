"""Stale-meter guardrail (review F5; invariant 7).

Fault on prolonged blindness (entity unavailable/unknown → None) while CHARGING.
Cadence-based freeze detection is deliberately NOT implemented: the one real
session (fixtures/real-swoop-asm-charge.csv) has a median 365 s / max 788 s gap
between updates with power flat across the gaps, so a frozen value is
indistinguishable from a normal CV plateau (spec stale-meter-guardrail, D1).

Scenarios A–D from bdd/ha-adapter/stale-meter-guardrail-bdd.md:
  A - brief unavailability then recovery → no fault
  B - meter goes dark → hold safely + meter_unavailable breadcrumb
  C - prolonged blindness while charging → STALE_METER fault
  D - recovery before threshold clears the blind-run clock
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
    SessionController,
    SessionState,
)
from custom_components.cyclesteward.coordinator import CyclestewardCoordinator
from custom_components.cyclesteward.watcher import HASensorWatcher

BDD_DIR = Path(__file__).resolve().parents[1] / "bdd" / "ha-adapter"

# Midnight UTC so morning-reset (06:00) never fires across these short runs.
_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_STALE_S = 1800.0


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


def _charging_controller() -> SessionController:
    cfg = GuardrailsConfig(stale_meter_fault_seconds=_STALE_S)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
    ctrl.tick(80.0, None, _T0)  # TURN_ON → CHARGING
    assert ctrl.state == SessionState.CHARGING
    return ctrl


# ── Direct evaluator unit tests ───────────────────────────────────────────────


def test_evaluator_no_fault_below_threshold():
    ev = GuardrailEvaluator(GuardrailsConfig(stale_meter_fault_seconds=_STALE_S))
    assert ev.check_stale_meter(True, _T0) is None              # blind run starts
    assert ev.check_stale_meter(True, _t(seconds=1799)) is None  # 1799 s < 1800 s


def test_evaluator_faults_at_threshold():
    ev = GuardrailEvaluator(GuardrailsConfig(stale_meter_fault_seconds=_STALE_S))
    ev.check_stale_meter(True, _T0)
    result = ev.check_stale_meter(True, _t(seconds=1800))
    assert result is not None
    assert result.fault == GuardrailFault.STALE_METER
    assert result.is_session_fault


def test_evaluator_measures_wall_clock_not_tick_count():
    """Two calls 1801 s apart fault, even though only two ticks occurred."""
    ev = GuardrailEvaluator(GuardrailsConfig(stale_meter_fault_seconds=_STALE_S))
    ev.check_stale_meter(True, _T0)
    assert ev.check_stale_meter(True, _t(seconds=1801)) is not None


def test_evaluator_recovery_clears_blind_run():
    ev = GuardrailEvaluator(GuardrailsConfig(stale_meter_fault_seconds=_STALE_S))
    ev.check_stale_meter(True, _T0)
    assert ev.check_stale_meter(False, _t(seconds=1000)) is None  # recovered → cleared
    # A new blind run must accrue a fresh 1800 s from the new start.
    ev.check_stale_meter(True, _t(seconds=1001))
    assert ev.check_stale_meter(True, _t(seconds=1001 + 1799)) is None
    assert ev.check_stale_meter(True, _t(seconds=1001 + 1800)) is not None


def test_evaluator_reset_clears_blind_run():
    ev = GuardrailEvaluator(GuardrailsConfig(stale_meter_fault_seconds=_STALE_S))
    ev.check_stale_meter(True, _T0)
    ev.reset()
    # Fresh run after reset: 1799 s past the reset's new start does not fault.
    ev.check_stale_meter(True, _t(seconds=1))
    assert ev.check_stale_meter(True, _t(seconds=1 + 1799)) is None


# ── Scenario C: prolonged blindness while charging → STALE_METER fault ─────────


def test_C_charging_blind_faults_after_threshold():
    ctrl = _charging_controller()
    ctrl.tick(None, None, _t(seconds=60))  # blind run starts at +60 s
    r = ctrl.tick(None, None, _t(seconds=60 + 1800))
    assert r.action == SessionAction.TURN_OFF
    assert r.state == SessionState.FAULTED
    assert r.fault == GuardrailFault.STALE_METER
    assert "blind" in r.reason.lower()


def test_C_event_log_records_stale_meter_fault():
    ctrl = _charging_controller()
    ctrl.tick(None, None, _t(seconds=60))
    ctrl.tick(None, None, _t(seconds=60 + 1800))
    assert any("stale_meter" in entry for entry in ctrl.event_log)


def test_C_no_fault_just_below_threshold():
    ctrl = _charging_controller()
    ctrl.tick(None, None, _t(seconds=60))
    r = ctrl.tick(None, None, _t(seconds=60 + 1799))
    assert r.state == SessionState.CHARGING
    assert r.fault is None
    assert "unavailable" in r.reason.lower()


# ── Scenario A/D: recovery clears the blind-run clock ──────────────────────────


def test_D_recovery_before_threshold_clears_clock():
    ctrl = _charging_controller()
    ctrl.tick(None, None, _t(seconds=60))    # blind start +60
    ctrl.tick(None, None, _t(seconds=600))   # 540 s blind, still holding
    r = ctrl.tick(85.0, None, _t(seconds=700))  # numeric reading recovers
    assert r.state == SessionState.CHARGING
    assert r.fault is None
    # A fresh blind run must accrue the full 1800 s again.
    ctrl.tick(None, None, _t(seconds=800))   # new blind start +800
    r = ctrl.tick(None, None, _t(seconds=800 + 1799))
    assert r.fault is None
    r = ctrl.tick(None, None, _t(seconds=800 + 1800))
    assert r.fault == GuardrailFault.STALE_METER


# ── Edge: blindness outside CHARGING never faults ─────────────────────────────


def test_blindness_outside_charging_does_not_fault():
    cfg = GuardrailsConfig(stale_meter_fault_seconds=_STALE_S)
    ctrl = SessionController(_calibrated_profile(), guardrails_config=cfg)
    ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)  # IDLE; None power never starts a charge
    for s in (0, 600, 1200, 2400, 4000):
        r = ctrl.tick(None, None, _t(seconds=s))
        assert r.state != SessionState.FAULTED
        assert r.fault is None


# ── Watcher observability: meter_unavailable / meter_recovered breadcrumbs ─────


def _make_hass() -> SimpleNamespace:
    plug_mock = SimpleNamespace(state="off")
    return SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: plug_mock),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=MagicMock()),
    )


def _fired_events(hass) -> list:
    """Names of cyclesteward_event events fired on the bus, in order."""
    return [
        call.args[1]["event"]
        for call in hass.bus.async_fire.call_args_list
        if call.args and call.args[0] == "cyclesteward_event"
    ]


def _make_charging_watcher():
    coordinator = CyclestewardCoordinator(
        _calibrated_profile(),
        guardrails_config=GuardrailsConfig(stale_meter_fault_seconds=_STALE_S),
    )
    coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
    hass = _make_hass()
    watcher = HASensorWatcher(
        hass=hass,
        coordinator=coordinator,
        power_entity_id="sensor.plug_power",
        plug_entity_id="switch.plug",
    )
    asyncio.run(watcher._do_tick(80.0, _T0))  # → CHARGING
    assert coordinator.session_state == SessionState.CHARGING
    return watcher, coordinator, hass


def test_watcher_fires_meter_unavailable_once_on_transition():
    watcher, _coord, hass = _make_charging_watcher()
    asyncio.run(watcher._do_tick(None, _t(seconds=60)))   # numeric → None
    asyncio.run(watcher._do_tick(None, _t(seconds=120)))  # still blind, no new event
    assert _fired_events(hass).count("meter_unavailable") == 1
    assert "meter_recovered" not in _fired_events(hass)


def test_watcher_fires_meter_recovered_on_resume():
    watcher, _coord, hass = _make_charging_watcher()
    asyncio.run(watcher._do_tick(None, _t(seconds=60)))    # blind
    asyncio.run(watcher._do_tick(85.0, _t(seconds=120)))   # recovered
    events = _fired_events(hass)
    assert events.count("meter_unavailable") == 1
    assert events.count("meter_recovered") == 1


# ── Anchor artifact: stale-meter decision trace ───────────────────────────────


def test_generate_stale_meter_trace():
    """Produce the anchor artifact: a JSON trace showing the fault and recovery legs.

    Saved to bdd/ha-adapter/stale-meter-guardrail-trace.json.
    """

    def run_leg(samples):
        cfg = GuardrailsConfig(stale_meter_fault_seconds=_STALE_S)
        ctrl = SessionController(_calibrated_profile(), guardrails_config=cfg)
        ctrl.set_mode(ChargeMode.CHARGE_TO_TARGET)
        events = []
        for seconds, power in samples:
            now = _T0 + timedelta(seconds=seconds)
            result = ctrl.tick(power, None, now)
            events.append(
                {"timestamp": now.isoformat(), "power_w": power, **result.to_dict()}
            )
        return ctrl, events

    # Fault leg: CHARGING, then blind from +60 s until the 1800 s threshold.
    fault_samples = [
        (0, 80.0),       # TURN_ON → CHARGING
        (60, None),      # blind run starts
        (600, None),     # 540 s blind, holding
        (1200, None),    # 1140 s blind, holding
        (1859, None),    # 1799 s blind, still holding
        (1860, None),    # 1800 s blind → STALE_METER fault
        (1920, None),    # latch check: stays FAULTED
    ]
    fault_ctrl, fault_events = run_leg(fault_samples)

    # Recovery leg: blind for under threshold, then a numeric reading resumes.
    recovery_samples = [
        (0, 80.0),       # TURN_ON → CHARGING
        (60, None),      # blind run starts
        (600, None),     # 540 s blind, holding
        (700, 85.0),     # numeric reading recovers; clock cleared
        (760, 88.0),     # continues charging normally
    ]
    _recovery_ctrl, recovery_events = run_leg(recovery_samples)

    fault_event_ts = next(
        e["timestamp"] for e in fault_events if e.get("fault") == "stale_meter"
    )

    trace = {
        "scenario": "stale-meter: CHARGING → blind (None) → STALE_METER fault; plus recovery leg",
        "config": {"stale_meter_fault_seconds": _STALE_S},
        "real_data_note": (
            "Cadence-based freeze detection intentionally omitted: "
            "fixtures/real-swoop-asm-charge.csv has median 365 s / max 788 s gaps "
            "with flat power, indistinguishable from a frozen meter (spec D1)."
        ),
        "fault_leg": fault_events,
        "recovery_leg": recovery_events,
        "expected": {
            "fault_leg_fault": "stale_meter",
            "fault_leg_fault_timestamp": fault_event_ts,
            "fault_leg_final_state": "faulted",
            "fault_leg_event_log": list(fault_ctrl.event_log),
            "recovery_leg_fault": None,
            "recovery_leg_final_state": "charging",
        },
    }

    BDD_DIR.mkdir(parents=True, exist_ok=True)
    out = BDD_DIR / "stale-meter-guardrail-trace.json"
    out.write_text(json.dumps(trace, indent=2) + "\n")

    # Verify artifact content on disk.
    data = json.loads(out.read_text())
    fault_states = [e["state"] for e in data["fault_leg"]]
    fault_faults = [e.get("fault") for e in data["fault_leg"]]
    recovery_faults = [e.get("fault") for e in data["recovery_leg"]]

    assert "charging" in fault_states
    assert fault_states[-1] == "faulted"
    assert "stale_meter" in fault_faults
    assert data["expected"]["fault_leg_fault_timestamp"] == _t(seconds=1860).isoformat()
    assert all(f is None for f in recovery_faults)
    assert data["recovery_leg"][-1]["state"] == "charging"
    assert any("stale_meter" in entry for entry in data["expected"]["fault_leg_event_log"])
