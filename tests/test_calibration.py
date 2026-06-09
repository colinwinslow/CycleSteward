"""Calibration profile model — BDD scenarios A, A2, B, C, D, E, F, F2, G, G2, G3, H."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    SocReport,
)
from cyclesteward.landmarks import CALIBRATION_DISTRUST, TAPER_AMBIGUOUS
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


# ── Scenario F: opportunistic full-session is promoted ────────────────────────


def _calibrated_profile(summary) -> CalibrationProfile:
    """Helper: return a CALIBRATED profile from a clean session summary."""
    profile = CalibrationProfile(
        charger_label="c", battery_label="b", meter_id="m", rated_capacity_wh=500.0
    )
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )
    assert profile.state == ProfileState.CALIBRATED
    return profile


def test_opportunistic_session_is_promoted(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary)

    promoted, reason = profile.classify_opportunistic_session(
        summary, temperature_c=21.0, timestamp=_TS
    )

    assert promoted is True
    assert len(profile.temperature_observations) == 1
    obs = profile.temperature_observations[0]
    assert obs.temperature_c == 21.0
    assert obs.active_wh == profile.active_full_wh


def test_opportunistic_session_stores_temperature_wh_pair(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary)

    profile.classify_opportunistic_session(summary, temperature_c=19.5, timestamp=_TS)
    profile.classify_opportunistic_session(summary, temperature_c=5.0, timestamp=_TS)

    assert len(profile.temperature_observations) == 2
    temps = [obs.temperature_c for obs in profile.temperature_observations]
    assert 19.5 in temps
    assert 5.0 in temps


def test_opportunistic_promotion_appears_in_json(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary)
    profile.classify_opportunistic_session(summary, temperature_c=21.0, timestamp=_TS)

    data = json.loads(profile.to_json())
    assert len(data["temperature_observations"]) == 1
    assert data["temperature_observations"][0]["temperature_c"] == 21.0


# ── Scenario F2: inrush settling selects settled watts_at_low ─────────────────


def test_inrush_fixture_calibrated_with_settled_watts_at_low(inrush_fixture):
    # The inrush-settling fixture has onset at ~46 W but the settled CC is 70.2 W.
    # After F2, watts_at_low in the calibration profile should reflect 70.2 W.
    parsed = parse_csv(inrush_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )

    assert profile.state == ProfileState.CALIBRATED
    assert profile.watts_at_low is not None
    assert profile.watts_at_low.watts == 70.2


# ── Scenario G: session starting too far from anchor is rejected ──────────────


def test_session_far_from_anchor_not_promoted(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary)

    # Construct a summary whose watts_at_low is 20% above the anchor (69 W).
    from cyclesteward.landmarks import Anchors, Landmarks
    from cyclesteward.profile import ProfileSummary

    far_summary = ProfileSummary(
        profile_id="far",
        sample_count=10,
        idle_power_w=1.8,
        anchors=Anchors(
            watts_at_low=90.0,  # clearly not near display-empty
            watts_at_transition=100.0,
            taper_floor_w=10.0,
        ),
        active_full_wh=400.0,
        landmarks=Landmarks(),
        warnings=[],
    )

    promoted, reason = profile.classify_opportunistic_session(far_summary, temperature_c=20.0)

    assert promoted is False
    assert "not promoted" in reason
    assert len(profile.temperature_observations) == 0


# ── Scenario G2: incomplete session is rejected even if start is near anchor ──


def test_incomplete_session_not_promoted(fixtures_dir, clean_fixture):
    parsed_clean = parse_csv(clean_fixture)
    summary_clean = analyze(parsed_clean.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary_clean)

    # The interrupted fixture has CALIBRATION_DISTRUST (large gap).
    parsed_interrupted = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    summary_interrupted = analyze(
        parsed_interrupted.samples, profile_id="interrupted", idle_power_w=1.8
    )
    assert any(CALIBRATION_DISTRUST in w for w in summary_interrupted.warnings)

    promoted, reason = profile.classify_opportunistic_session(
        summary_interrupted, temperature_c=20.0
    )

    assert promoted is False
    assert "not promoted" in reason
    assert len(profile.temperature_observations) == 0


# ── Scenario G3: relay cutoff session is rejected ─────────────────────────────


def test_relay_cutoff_session_not_promoted(mid_taper_cutoff_fixture, clean_fixture):
    parsed_clean = parse_csv(clean_fixture)
    summary_clean = analyze(parsed_clean.samples, profile_id="x", idle_power_w=1.8)
    profile = _calibrated_profile(summary_clean)

    parsed_cutoff = parse_csv(mid_taper_cutoff_fixture)
    summary_cutoff = analyze(parsed_cutoff.samples, profile_id="cutoff", idle_power_w=1.8)
    assert any(TAPER_AMBIGUOUS in w for w in summary_cutoff.warnings)

    promoted, reason = profile.classify_opportunistic_session(
        summary_cutoff, temperature_c=20.0
    )

    assert promoted is False
    assert "relay cutoff" in reason
    assert len(profile.temperature_observations) == 0


def test_uncalibrated_profile_rejects_opportunistic(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    profile = CalibrationProfile(charger_label="c", battery_label="b", meter_id="m")

    promoted, reason = profile.classify_opportunistic_session(summary)

    assert promoted is False
    assert "not yet calibrated" in reason


# ── Scenario H: calibration on imported Home Assistant history ────────────────


def test_ha_exported_rows_produce_profile_output(fixtures_dir):
    # real-swoop-asm-charge.csv is derived from an actual HA history export.
    # The core must ingest it without importing Home Assistant.
    parsed = parse_csv(fixtures_dir / "real-swoop-asm-charge.csv")
    assert parsed.warnings == []

    summary = analyze(parsed.samples, profile_id="ha-import:swoop")
    profile = CalibrationProfile(
        charger_label="swoop-charger",
        battery_label="asm-battery",
        meter_id="sensor.swoop_plug",
    )
    profile.ingest_full_session(
        summary, soc_at_start=SocReport.display_empty(), timestamp=_TS
    )

    # The HA-derived session produces valid anchors even after relay-cutoff fix.
    assert profile.watts_at_low is not None
    assert profile.watts_at_transition is not None
    # Taper floor is None (relay cutoff detected); that is correct behaviour.
    assert profile.taper_floor_w is None
    data = json.loads(profile.to_json())
    assert data["watts_at_low"] is not None
    assert data["watts_at_transition"] is not None


def test_ha_export_tolerates_unknown_rows(fixtures_dir):
    # synthetic-with-unknown-rows.csv has unknown/unavailable power and temp
    # values; the parser must skip them and still produce usable samples.
    parsed = parse_csv(fixtures_dir / "synthetic-with-unknown-rows.csv")
    skipped = [w for w in parsed.warnings if "skipped" in w]
    assert len(skipped) >= 2, "expected at least 2 skipped-row warnings"
    assert len(parsed.samples) > 0


def test_ha_core_has_no_homeassistant_import():
    # ADR-0010: the pure core must not import Home Assistant.
    import cyclesteward.calibration as cal_mod
    import cyclesteward.profile as prof_mod
    import cyclesteward.landmarks as lm_mod

    for mod in (cal_mod, prof_mod, lm_mod):
        assert "homeassistant" not in dir(mod)
