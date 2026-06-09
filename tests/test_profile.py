"""End-to-end analyze() behavior and the deterministic profile-summary artifact."""

from __future__ import annotations

import json

from cyclesteward.profile import analyze
from cyclesteward.samples import parse_csv


def test_analyze_clean_fixture_summary(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="fixture:synthetic-low-to-full", idle_power_w=1.8)
    data = summary.to_dict()

    assert data["schema_version"] == 1
    assert data["profile_id"] == "fixture:synthetic-low-to-full"
    assert data["sample_count"] == 49
    assert data["idle_power_w"] == 1.8
    assert data["anchors"] == {
        "watts_at_low": 69.0,
        "watts_at_transition": 84.0,
        "taper_floor_w": 18.0,
    }
    # Active Wh is the calibration aid; positive and in a sane band for this curve.
    assert 350.0 < data["active_full_wh"] < 550.0
    assert data["landmarks"]["completion_timestamp"] == "2026-06-09T01:10:00-07:00"
    assert data["warnings"] == []


def test_idle_is_estimated_when_not_supplied(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x")
    assert summary.idle_power_w == 1.8  # lowest reading in the fixture


def test_summary_is_deterministic(clean_fixture):
    parsed = parse_csv(clean_fixture)
    first = analyze(parsed.samples, profile_id="x", idle_power_w=1.8).to_json()
    second = analyze(parsed.samples, profile_id="x", idle_power_w=1.8).to_json()
    assert first == second


def test_to_json_is_valid_and_round_trips(clean_fixture):
    parsed = parse_csv(clean_fixture)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8)
    reparsed = json.loads(summary.to_json())
    assert reparsed["anchors"]["watts_at_transition"] == 84.0


def test_input_warnings_propagate_to_summary():
    from cyclesteward.samples import parse_rows

    rows = [
        {"timestamp": "2026-06-08T18:00:00-07:00", "power_w": "1.8"},
        {"timestamp": "2026-06-08T18:10:00-07:00", "power_w": "unknown"},
        {"timestamp": "2026-06-08T18:20:00-07:00", "power_w": "69.0"},
    ]
    parsed = parse_rows(rows)
    summary = analyze(parsed.samples, profile_id="x", idle_power_w=1.8, input_warnings=parsed.warnings)
    assert any("skipped" in warning for warning in summary.warnings)
