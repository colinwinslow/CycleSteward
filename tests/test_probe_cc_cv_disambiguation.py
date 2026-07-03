"""Tests for probe CC/CV disambiguation and SoC taper latch (packet 5 / F7).

Covers:
  - _classify_probe_trend() unit tests (CC, CV, insufficient, edge cases)
  - Watcher: CC probe concludes after min samples, computed_start_time updated
  - Watcher: CV taper probe concludes after min samples, start time pushed late
  - Watcher: probe timeout with insufficient samples falls back to pessimistic
  - Watcher: probe timeout with enough samples classifies at timeout
  - Produces bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json anchor artifact
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.session_control import (
    ChargeMode,
    SessionConfig,
    SessionState,
)
from custom_components.cyclesteward.coordinator import CyclestewardCoordinator
from custom_components.cyclesteward.watcher import (
    HASensorWatcher,
    _CV_FALLING_RATIO,
    _DEFAULT_MARGIN_S,
    _MIN_PROBE_SAMPLES,
)

BDD_DIR = Path(__file__).resolve().parents[1] / "bdd" / "ha-adapter"

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def t(seconds: int = 0, minutes: int = 0, hours: int = 0) -> datetime:
    return T0 + timedelta(seconds=seconds, minutes=minutes, hours=hours)


def _calibrated_profile(
    watts_at_low: float = 60.0,
    watts_at_transition: float = 80.0,
    taper_floor_w: float = 10.0,
) -> CalibrationProfile:
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="sensor.plug_power",
    )
    p.state = ProfileState.CALIBRATED
    p.watts_at_low = WattageAnchor(watts=watts_at_low, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(
        watts=watts_at_transition, assumed_soc_label="cc_cv_transition"
    )
    p.taper_floor_w = taper_floor_w
    p.active_full_wh = 400.0
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
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


def _drive_to_probing(watcher, coordinator, probe_time: datetime) -> None:
    """Drive the watcher into PROBING state."""
    run(watcher._do_tick(70.0, T0))
    run(watcher._do_tick(70.0, probe_time))
    assert coordinator.session_state == SessionState.PROBING


# ── _classify_probe_trend unit tests ─────────────────────────────────────────


class TestClassifyProbeTrend:
    def test_returns_none_when_insufficient_samples(self):
        watcher, _, _ = _make_watcher()
        # No samples
        assert watcher._classify_probe_trend() is None

    def test_returns_none_when_below_min_samples(self):
        watcher, _, _ = _make_watcher()
        now = T0
        for i in range(_MIN_PROBE_SAMPLES - 1):
            watcher._probe_samples.append((now + timedelta(seconds=i), 70.0))
        assert watcher._classify_probe_trend() is None

    def test_flat_wattage_classified_as_cc(self):
        watcher, _, _ = _make_watcher()
        now = T0
        for i in range(_MIN_PROBE_SAMPLES):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), 70.0))
        assert watcher._classify_probe_trend() == "cc"

    def test_rising_wattage_classified_as_cc(self):
        watcher, _, _ = _make_watcher()
        now = T0
        for i, w in enumerate([65.0, 68.0, 70.0, 72.0]):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), w))
        assert watcher._classify_probe_trend() == "cc"

    def test_falling_wattage_classified_as_cv_taper(self):
        watcher, _, _ = _make_watcher()
        now = T0
        for i, w in enumerate([78.0, 72.0, 65.0, 57.0, 50.0, 43.0]):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), w))
        assert watcher._classify_probe_trend() == "cv_taper"

    def test_small_drop_within_ratio_still_cc(self):
        """A drop of exactly cv_falling_ratio is still CC (boundary)."""
        watcher, _, _ = _make_watcher()
        now = T0
        # last_mean / first_mean == _CV_FALLING_RATIO → CC
        w_first = 70.0
        w_last = w_first * _CV_FALLING_RATIO
        for i, w in enumerate([w_first, w_first, w_last, w_last]):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), w))
        assert watcher._classify_probe_trend() == "cc"

    def test_drop_just_below_ratio_is_cv_taper(self):
        watcher, _, _ = _make_watcher()
        now = T0
        w_first = 70.0
        w_last = w_first * (_CV_FALLING_RATIO - 0.01)
        for i, w in enumerate([w_first, w_first, w_last, w_last]):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), w))
        assert watcher._classify_probe_trend() == "cv_taper"

    def test_zero_first_mean_returns_cc(self):
        """Guard against division by zero when first_mean is 0."""
        watcher, _, _ = _make_watcher()
        now = T0
        for i in range(_MIN_PROBE_SAMPLES):
            watcher._probe_samples.append((now + timedelta(seconds=i * 10), 0.0))
        assert watcher._classify_probe_trend() == "cc"


# ── Scenario A: CC probe classifies correctly and updates start time ──────────


class TestCCProbeClassification:
    def test_cc_probe_concludes_after_min_samples(self):
        """Flat CC wattage: probe concludes after _MIN_PROBE_SAMPLES, returns WAITING."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, _ = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        # Feed _MIN_PROBE_SAMPLES flat CC readings
        for i in range(_MIN_PROBE_SAMPLES):
            run(watcher._do_tick(65.0, pt + timedelta(seconds=10 * (i + 1))))

        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

    def test_cc_probe_updates_computed_start_time_later(self):
        """CC probe refines computed_start_time to later than the pessimistic default."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, _ = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pessimistic = watcher.computed_start_time
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        for i in range(_MIN_PROBE_SAMPLES):
            run(watcher._do_tick(65.0, pt + timedelta(seconds=10 * (i + 1))))

        refined = watcher.computed_start_time
        assert refined is not None
        assert refined >= pessimistic

    def test_cc_probe_fires_event_with_classification_field(self):
        """probe_result event contains classification='cc'."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, hass = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        for i in range(_MIN_PROBE_SAMPLES):
            run(watcher._do_tick(65.0, pt + timedelta(seconds=10 * (i + 1))))

        fired = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        probe_results = [e for e in fired if e["event"] == "probe_result"]
        assert len(probe_results) >= 1
        assert probe_results[-1]["classification"] == "cc"

    def test_cc_probe_samples_cleared_after_conclusion(self):
        """_probe_samples is empty after the probe concludes."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, _ = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        for i in range(_MIN_PROBE_SAMPLES):
            run(watcher._do_tick(65.0, pt + timedelta(seconds=10 * (i + 1))))

        assert watcher._probe_samples == []


# ── Scenario B: CV taper probe pushes start time late ────────────────────────


class TestCVTaperProbeClassification:
    def test_cv_taper_probe_concludes_after_min_samples(self):
        """Falling wattage: probe concludes after _MIN_PROBE_SAMPLES, returns WAITING."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, _ = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        # Falling readings: 78→43 W is a clear CV taper
        for i, w in enumerate([78.0, 65.0, 50.0]):
            run(watcher._do_tick(w, pt + timedelta(seconds=10 * (i + 1))))

        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE

    def test_cv_taper_probe_pushes_start_time_to_target_minus_margin(self):
        """CV taper: computed_start_time = target_finish_time - margin_s."""
        margin_s = 1800.0
        target = T0 + timedelta(hours=8)
        watcher, coordinator, _ = _make_watcher(
            target_finish_time=target, margin_s=margin_s
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        for i, w in enumerate([78.0, 65.0, 50.0]):
            run(watcher._do_tick(w, pt + timedelta(seconds=10 * (i + 1))))

        expected = target - timedelta(seconds=margin_s)
        assert watcher.computed_start_time == expected

    def test_cv_taper_probe_fires_event_with_classification_and_means(self):
        """probe_result event contains classification='cv_taper', first_mean_w, last_mean_w."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, hass = _make_watcher(target_finish_time=target)
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        for i, w in enumerate([78.0, 65.0, 50.0]):
            run(watcher._do_tick(w, pt + timedelta(seconds=10 * (i + 1))))

        fired = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        probe_results = [e for e in fired if e["event"] == "probe_result"]
        assert len(probe_results) >= 1
        result = probe_results[-1]
        assert result["classification"] == "cv_taper"
        assert "first_mean_w" in result
        assert "last_mean_w" in result
        assert result["last_mean_w"] < result["first_mean_w"]


# ── Scenario C: insufficient samples falls back to pessimistic ───────────────


class TestInsufficientSamplesTimeout:
    def test_timeout_with_no_samples_uses_pessimistic(self):
        """Probe times out with zero readings: pessimistic fallback, no classification."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, hass = _make_watcher(
            target_finish_time=target, max_probe_seconds=30.0
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        pessimistic = watcher.computed_start_time
        _drive_to_probing(watcher, coordinator, pt)

        # Send None readings (meter unavailable) so no samples accumulate
        for i in range(4):
            run(watcher._do_tick(None, pt + timedelta(seconds=10 * (i + 1))))

        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE
        assert watcher.computed_start_time == pessimistic
        fired = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        timeout_events = [e for e in fired if e["event"] == "probe_result"]
        assert len(timeout_events) >= 1
        assert "classification" not in timeout_events[-1]

    def test_timeout_with_enough_samples_classifies(self):
        """Probe times out but has >= _MIN_PROBE_SAMPLES: classification runs."""
        target = T0 + timedelta(hours=8)
        watcher, coordinator, hass = _make_watcher(
            target_finish_time=target, max_probe_seconds=25.0
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        watcher.set_target_finish_time(target)
        pt = watcher._probe_time()
        _drive_to_probing(watcher, coordinator, pt)

        # Inject 3 flat CC readings into probe_samples directly (before timeout tick)
        for i in range(_MIN_PROBE_SAMPLES):
            watcher._probe_samples.append((pt + timedelta(seconds=i * 5), 65.0))

        # Trigger timeout (past max_probe_seconds=25s)
        run(watcher._do_tick(65.0, pt + timedelta(seconds=26)))

        assert coordinator.session_state == SessionState.WAITING_FOR_SCHEDULE
        fired = [call[0][1] for call in hass.bus.async_fire.call_args_list]
        probe_results = [e for e in fired if e["event"] == "probe_result"]
        assert any("classification" in e for e in probe_results)


# ── Anchor artifact: deterministic trace ─────────────────────────────────────


def test_generate_probe_cc_cv_disambiguation_trace():
    """Produce the anchor trace JSON for BDD scenarios A–D.

    Four legs:
      1. CC-classified probe (flat wattage) → computed_start_time updated.
      2. CV-taper probe (falling wattage) → computed_start_time pushed late.
      3. Probe timeout with insufficient samples → pessimistic fallback, no classification.
      4. SoC latch during CHARGE_TO_FULL taper (from session_control tests).
    """
    from cyclesteward.session_control import SessionController

    target = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
    margin_s = 1800.0
    profile = _calibrated_profile(watts_at_low=60.0, watts_at_transition=80.0)

    # ── Leg 1: CC probe ────────────────────────────────────────────────────────
    watcher_cc, coordinator_cc, hass_cc = _make_watcher(
        profile=profile, target_finish_time=target, margin_s=margin_s
    )
    coordinator_cc.set_mode(ChargeMode.CHARGE_TO_TARGET)
    watcher_cc.set_target_finish_time(target)
    pessimistic_cc = watcher_cc.computed_start_time
    pt_cc = watcher_cc._probe_time()

    cc_events = []
    run(watcher_cc._do_tick(65.0, T0))
    cc_events.append({"ts": T0.isoformat(), "power_w": 65.0, "state": coordinator_cc.session_state.value, "note": "initial tick"})
    run(watcher_cc._do_tick(65.0, pt_cc))
    cc_events.append({"ts": pt_cc.isoformat(), "power_w": 65.0, "state": coordinator_cc.session_state.value, "note": "probe fired"})

    probe_watts = [65.0, 66.0, 65.0]
    for i, w in enumerate(probe_watts):
        tick_t = pt_cc + timedelta(seconds=10 * (i + 1))
        run(watcher_cc._do_tick(w, tick_t))
        cc_events.append({"ts": tick_t.isoformat(), "power_w": w, "state": coordinator_cc.session_state.value, "note": f"probe sample {i+1}"})

    cc_probe_result = next(
        (call[0][1] for call in hass_cc.bus.async_fire.call_args_list
         if call[0][1]["event"] == "probe_result"), None
    )

    # ── Leg 2: CV taper probe ─────────────────────────────────────────────────
    watcher_cv, coordinator_cv, hass_cv = _make_watcher(
        profile=profile, target_finish_time=target, margin_s=margin_s
    )
    coordinator_cv.set_mode(ChargeMode.CHARGE_TO_TARGET)
    watcher_cv.set_target_finish_time(target)
    pt_cv = watcher_cv._probe_time()

    cv_events = []
    run(watcher_cv._do_tick(70.0, T0))
    cv_events.append({"ts": T0.isoformat(), "power_w": 70.0, "state": coordinator_cv.session_state.value, "note": "initial tick"})
    run(watcher_cv._do_tick(70.0, pt_cv))
    cv_events.append({"ts": pt_cv.isoformat(), "power_w": 70.0, "state": coordinator_cv.session_state.value, "note": "probe fired"})

    taper_watts = [78.0, 65.0, 50.0]
    for i, w in enumerate(taper_watts):
        tick_t = pt_cv + timedelta(seconds=10 * (i + 1))
        run(watcher_cv._do_tick(w, tick_t))
        cv_events.append({"ts": tick_t.isoformat(), "power_w": w, "state": coordinator_cv.session_state.value, "note": f"probe sample {i+1}"})

    cv_probe_result = next(
        (call[0][1] for call in hass_cv.bus.async_fire.call_args_list
         if call[0][1]["event"] == "probe_result"), None
    )

    # ── Leg 3: Probe timeout with insufficient samples ────────────────────────
    watcher_to, coordinator_to, hass_to = _make_watcher(
        profile=profile, target_finish_time=target, margin_s=margin_s,
        max_probe_seconds=30.0,
    )
    coordinator_to.set_mode(ChargeMode.CHARGE_TO_TARGET)
    watcher_to.set_target_finish_time(target)
    pessimistic_to = watcher_to.computed_start_time
    pt_to = watcher_to._probe_time()

    to_events = []
    run(watcher_to._do_tick(65.0, T0))
    to_events.append({"ts": T0.isoformat(), "power_w": 65.0, "state": coordinator_to.session_state.value, "note": "initial tick"})
    run(watcher_to._do_tick(65.0, pt_to))
    to_events.append({"ts": pt_to.isoformat(), "power_w": 65.0, "state": coordinator_to.session_state.value, "note": "probe fired"})

    # Send None readings — meter unavailable, no samples accumulated
    for i in range(4):
        tick_t = pt_to + timedelta(seconds=10 * (i + 1))
        run(watcher_to._do_tick(None, tick_t))
        to_events.append({"ts": tick_t.isoformat(), "power_w": None, "state": coordinator_to.session_state.value, "note": f"meter unavailable (tick {i+1})"})

    to_probe_result = next(
        (call[0][1] for call in hass_to.bus.async_fire.call_args_list
         if call[0][1]["event"] == "probe_result"), None
    )

    # ── Leg 4: SoC latch during CHARGE_TO_FULL taper ─────────────────────────
    config = SessionConfig(taper_below_floor_seconds=60.0)
    ctrl = SessionController(profile, config)
    ctrl.set_mode(ChargeMode.CHARGE_TO_FULL)

    latch_events = []
    T_L = datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)

    def lt(s: int) -> datetime:
        return T_L + timedelta(seconds=s)

    r0 = ctrl.tick(75.0, None, lt(0))
    latch_events.append({"ts": lt(0).isoformat(), "power_w": 75.0, **r0.to_dict(), "note": "TURN_ON"})
    r1 = ctrl.tick(75.0, None, lt(60))
    peak_soc = r1.soc_estimate.estimated_soc_pct if r1.soc_estimate else None
    latch_events.append({"ts": lt(60).isoformat(), "power_w": 75.0, **r1.to_dict(), "note": f"peak SoC {peak_soc}"})
    r2 = ctrl.tick(8.0, None, lt(120))
    latch_events.append({"ts": lt(120).isoformat(), "power_w": 8.0, **r2.to_dict(), "note": "taper start; latch armed"})
    r3 = ctrl.tick(5.0, None, lt(150))
    latch_events.append({"ts": lt(150).isoformat(), "power_w": 5.0, **r3.to_dict(), "note": "falling wattage; latch holds"})
    r4 = ctrl.tick(3.0, None, lt(181))
    latch_events.append({"ts": lt(181).isoformat(), "power_w": 3.0, **r4.to_dict(), "note": "taper duration met; cutoff"})

    trace = {
        "description": "probe-cc-cv-disambiguation anchor trace",
        "min_probe_samples": _MIN_PROBE_SAMPLES,
        "cv_falling_ratio": _CV_FALLING_RATIO,
        "legs": {
            "cc_probe": {
                "description": "flat wattage during probe → CC classification → start time refined",
                "target_finish_time": target.isoformat(),
                "margin_s": margin_s,
                "pessimistic_start_time": pessimistic_cc.isoformat() if pessimistic_cc else None,
                "probe_time": pt_cc.isoformat() if pt_cc else None,
                "probe_watts": probe_watts,
                "events": cc_events,
                "probe_result_event": cc_probe_result,
                "computed_start_time_after": watcher_cc.computed_start_time.isoformat() if watcher_cc.computed_start_time else None,
                "expected": {
                    "classification": "cc",
                    "start_time_moved_later": True,
                },
            },
            "cv_taper_probe": {
                "description": "falling wattage during probe → CV taper classification → start pushed late",
                "probe_watts": taper_watts,
                "events": cv_events,
                "probe_result_event": cv_probe_result,
                "computed_start_time_after": watcher_cv.computed_start_time.isoformat() if watcher_cv.computed_start_time else None,
                "expected": {
                    "classification": "cv_taper",
                    "computed_start_time": (target - timedelta(seconds=margin_s)).isoformat(),
                },
            },
            "probe_timeout": {
                "description": "meter unavailable during probe → timeout → pessimistic fallback, no classification",
                "max_probe_seconds": 30.0,
                "pessimistic_start_time": pessimistic_to.isoformat() if pessimistic_to else None,
                "events": to_events,
                "probe_result_event": to_probe_result,
                "computed_start_time_after": watcher_to.computed_start_time.isoformat() if watcher_to.computed_start_time else None,
                "expected": {
                    "no_classification_field": True,
                    "computed_start_time_unchanged": True,
                },
            },
            "soc_latch": {
                "description": "CHARGE_TO_FULL taper: soc_estimate held at session max",
                "events": latch_events,
                "expected": {
                    "peak_soc_pct": peak_soc,
                    "latch_note_contains": "taper phase",
                    "latch_low_confidence": True,
                    "done_state": "done_latched_off",
                },
            },
        },
    }

    out = BDD_DIR / "probe-cc-cv-disambiguation-trace.json"
    out.write_text(json.dumps(trace, indent=2) + "\n")

    # ── Verify the artifact on disk ────────────────────────────────────────────
    data = json.loads(out.read_text())

    # CC leg
    cc_leg = data["legs"]["cc_probe"]
    assert cc_leg["probe_result_event"]["classification"] == "cc"
    assert cc_leg["probe_result_event"] is not None
    cc_after = datetime.fromisoformat(cc_leg["computed_start_time_after"])
    cc_pessimistic = datetime.fromisoformat(cc_leg["pessimistic_start_time"])
    assert cc_after >= cc_pessimistic, "CC probe should refine start time later"

    # CV leg
    cv_leg = data["legs"]["cv_taper_probe"]
    assert cv_leg["probe_result_event"]["classification"] == "cv_taper"
    assert "first_mean_w" in cv_leg["probe_result_event"]
    assert "last_mean_w" in cv_leg["probe_result_event"]
    cv_expected = datetime.fromisoformat(cv_leg["expected"]["computed_start_time"])
    cv_actual = datetime.fromisoformat(cv_leg["computed_start_time_after"])
    assert cv_actual == cv_expected, "CV taper should set start to target - margin"

    # Timeout leg
    to_leg = data["legs"]["probe_timeout"]
    assert to_leg["probe_result_event"] is not None
    assert "classification" not in to_leg["probe_result_event"], \
        "timeout probe_result must not have a classification field"
    assert to_leg["computed_start_time_after"] == to_leg["pessimistic_start_time"], \
        "timeout must not move computed_start_time"

    # SoC latch leg
    latch_leg = data["legs"]["soc_latch"]
    latch_event = next(e for e in latch_leg["events"] if "taper start" in e["note"])
    held_event = next(e for e in latch_leg["events"] if "falling wattage" in e["note"])
    done_event = next(e for e in latch_leg["events"] if "cutoff" in e["note"])

    assert latch_event["soc_estimate"]["note"] is not None
    assert "taper phase" in latch_event["soc_estimate"]["note"]
    assert held_event["soc_estimate"]["estimated_soc_pct"] == latch_event["soc_estimate"]["estimated_soc_pct"]
    assert held_event["soc_estimate"]["low_confidence"] is True
    assert done_event["state"] == "done_latched_off"
    assert done_event["soc_estimate"]["note"] is not None
    assert "taper phase" in done_event["soc_estimate"]["note"]
