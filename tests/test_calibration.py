"""Calibration profile model — BDD scenarios A, A2, B, C, D, E."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    SocReport,
)
from cyclesteward.landmarks import CALIBRATION_DISTRUST
from cyclesteward.profile import analyze
from cyclesteward.samples import parse_csv

_TS = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


# ── Scenario B: coarse SoC storage ───────────────────────────────────────────


def test_soc_report_from_dots_is_coarse():
    report = SocReport.from_dots(0, 5)
    assert report.coarse is True
    assert report.label == "0 of 5 dots"
    assert report.interval_low_pct == 0.0
    assert report.interval_high_pct == 20.0


def test_soc_report_from_dots_spans_a_range():
    """Zero dots is NOT stored as exact 0% — the interval has positive width."""
    report = SocReport.from_dots(0, 5)
    assert report.interval_high_pct > report.interval_low_pct
    d = report.to_dict()
    assert d["interval_high_pct"] > d["interval_low_pct"]


def test_soc_report_from_dots_mid_range():
    report = SocReport.from_dots(3, 5)
    assert report.coarse is True
    assert report.interval_low_pct == 60.0
    assert report.interval_high_pct == 80.0


def test_soc_report_display_empty_is_coarse():
    report = SocReport.display_empty()
    assert report.coarse is True
    assert report.label == "display_empty"
    assert report.interval_high_pct > report.interval_low_pct


# ── Scenario A: full calibration stores anchors ───────────────────────────────


def test_full_calibration_stores_wattage_anchors(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="test:full-calib", idle_power_w=1.8)

    profile = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="sensor.test_power",
    )
    profile.ingest_full_session(
        summary,
        soc_at_start=SocReport.display_empty(),
        assumptions=SocAssumptions(),
        timestamp=_TS,
    )

    assert profile.state == ProfileState.CALIBRATED
    assert profile.watts_at_low is not None
    assert profile.watts_at_low.watts == 69.0
    assert profile.watts_at_transition is not None
    assert profile.watts_at_transition.watts == 84.0
    assert profile.taper_floor_w == 18.0
    assert profile.idle_power_w == 1.8
    assert profile.active_full_wh is not None
    assert 350.0 < profile.active_full_wh < 550.0
    assert len(profile.full_observations) == 1
    assert profile.full_observations[0].trusted is True
    assert profile.warnings == []


def test_full_calibration_json_has_expected_shape(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="test:full-calib", idle_power_w=1.8)
    profile = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="sensor.test_power",
    )
    profile.ingest_full_session(
        summary,
        soc_at_start=SocReport.display_empty(),
        timestamp=_TS,
    )
    data = json.loads(profile.to_json())

    assert data["schema_version"] == 1
    assert data["state"] == "calibrated"
    assert data["watts_at_low"]["watts"] == 69.0
    assert data["watts_at_low"]["assumed_soc_label"] == "display_empty"
    assert data["watts_at_transition"]["watts"] == 84.0
    assert data["watts_at_transition"]["assumed_soc_label"] == "cc_cv_transition"
    assert data["taper_floor_w"] == 18.0
    assert len(data["full_observations"]) == 1
    assert data["full_observations"][0]["trusted"] is True


def test_initial_state_is_uncalibrated():
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    assert profile.state == ProfileState.UNCALIBRATED


# ── Scenario A2: active Wh locates the target wattage ─────────────────────────


def test_target_wattage_80pct_equals_transition_when_assumptions_match(clean_fixture):
    """soc_at_transition=80%, target=80% → result is watts_at_transition."""
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary,
        assumptions=SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0),
        timestamp=_TS,
    )

    target = profile.target_wattage(80.0)

    assert target is not None
    assert abs(target - 84.0) < 0.01


def test_target_wattage_interpolates_midpoint(clean_fixture):
    """40% SoC (midpoint of 0–80) → midpoint of 69–84 = 76.5 W."""
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary,
        assumptions=SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0),
        timestamp=_TS,
    )

    target = profile.target_wattage(40.0)

    assert target is not None
    assert abs(target - 76.5) < 0.01


def test_target_wattage_at_low_anchor(clean_fixture):
    """0% SoC target → watts_at_low."""
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary,
        assumptions=SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0),
        timestamp=_TS,
    )

    target = profile.target_wattage(0.0)

    assert target is not None
    assert abs(target - 69.0) < 0.01


def test_target_wattage_returns_none_when_uncalibrated():
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    assert profile.target_wattage(80.0) is None


# ── Scenario C: partial observation does not overwrite full calibration ────────


def test_partial_does_not_overwrite_active_full_wh(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )
    assert profile.state == ProfileState.CALIBRATED
    original_wh = profile.active_full_wh

    partial_summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile.ingest_partial_session(
        partial_summary,
        soc_at_start=SocReport.from_dots(3, 5),
        timestamp=_TS,
    )

    assert profile.active_full_wh == original_wh
    assert profile.state == ProfileState.CALIBRATED
    assert len(profile.partial_observations) == 1
    assert profile.partial_observations[0].soc_at_start.label == "3 of 5 dots"


def test_partial_soc_report_stored_as_coarse(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)
    profile.ingest_partial_session(
        summary, soc_at_start=SocReport.from_dots(3, 5), timestamp=_TS
    )

    partial_soc = profile.partial_observations[0].soc_at_start
    assert partial_soc.coarse is True
    assert partial_soc.interval_high_pct > partial_soc.interval_low_pct


def test_partial_appears_in_json(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)
    profile.ingest_partial_session(
        summary, soc_at_start=SocReport.from_dots(3, 5), timestamp=_TS
    )

    data = json.loads(profile.to_json())
    assert len(data["partial_observations"]) == 1
    assert data["partial_observations"][0]["soc_at_start"]["label"] == "3 of 5 dots"
    assert data["partial_observations"][0]["soc_at_start"]["coarse"] is True


# ── Scenario D: bad sample data is rejected for calibration ──────────────────


def test_interrupted_session_not_trusted(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    assert any(CALIBRATION_DISTRUST in w for w in summary.warnings)

    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )

    assert profile.state != ProfileState.CALIBRATED
    assert len(profile.warnings) > 0
    assert len(profile.full_observations) == 1
    assert profile.full_observations[0].trusted is False


def test_untrusted_session_leaves_anchors_unset(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)

    assert profile.watts_at_low is None
    assert profile.watts_at_transition is None
    assert profile.active_full_wh is None


def test_bad_session_transitions_to_calibrating(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)

    assert profile.state == ProfileState.CALIBRATING


def test_quality_flags_recorded_in_observation(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)

    obs = profile.full_observations[0]
    assert len(obs.quality_flags) > 0
    assert any(CALIBRATION_DISTRUST in flag for flag in obs.quality_flags)


# ── Scenario E: rated capacity yields an overhead estimate ────────────────────


def test_rated_capacity_yields_overhead_estimate(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(
        charger_label="c",
        battery_label="b",
        meter_id="m",
        rated_capacity_wh=500.0,
    )
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )

    assert profile.overhead is not None
    expected_ratio = summary.active_full_wh / 500.0
    assert abs(profile.overhead.ratio - expected_ratio) < 0.001
    assert profile.overhead.confidence == "low"
    assert profile.overhead.rated_capacity_wh == 500.0
    assert profile.overhead.measured_full_wh == profile.active_full_wh


def test_no_overhead_when_rated_capacity_not_set(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(summary, timestamp=_TS)

    assert profile.overhead is None


def test_overhead_in_json_carries_uncertainty_note(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(
        charger_label="c", battery_label="b", meter_id="m", rated_capacity_wh=500.0
    )
    profile.ingest_full_session(summary, timestamp=_TS)

    data = json.loads(profile.to_json())
    assert data["overhead"]["confidence"] == "low"
    assert "note" in data["overhead"]
    assert data["overhead"]["rated_capacity_wh"] == 500.0
