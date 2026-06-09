"""Curve-landmark and wattage-anchor detection."""

from __future__ import annotations

from cyclesteward.landmarks import CALIBRATION_DISTRUST, detect
from cyclesteward.samples import parse_csv


def test_clean_session_detects_anchors_and_landmarks(clean_fixture):
    parsed = parse_csv(clean_fixture)
    result = detect(parsed.samples, idle_w=1.8)

    assert result.anchors.watts_at_low == 69.00
    assert result.anchors.watts_at_transition == 84.00
    assert result.anchors.taper_floor_w == 18.00

    assert result.landmarks.peak_power_w == 84.00
    assert result.landmarks.active_start_timestamp.isoformat() == "2026-06-08T18:10:00-07:00"
    assert result.landmarks.peak_timestamp.isoformat() == "2026-06-08T23:00:00-07:00"
    assert result.landmarks.taper_start_timestamp.isoformat() == "2026-06-08T23:10:00-07:00"
    assert result.landmarks.completion_timestamp.isoformat() == "2026-06-09T01:10:00-07:00"

    assert result.warnings == []


def test_noisy_session_still_detects_anchors(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-noisy-low-to-full.csv")
    result = detect(parsed.samples, idle_w=2.0)

    # Anchors land on the right samples despite +/- noise; no fatal warnings.
    assert result.anchors.watts_at_low == 68.30
    assert result.anchors.watts_at_transition == 84.30
    assert result.landmarks.completion_timestamp is not None
    assert result.warnings == []


def test_interrupted_session_warns_about_gap(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "synthetic-interrupted.csv")
    result = detect(parsed.samples, idle_w=1.8)

    assert any(CALIBRATION_DISTRUST in warning for warning in result.warnings)
    assert any("interrupted" in warning for warning in result.warnings)


def test_no_active_charging_warns():
    from datetime import datetime, timedelta, timezone

    from cyclesteward.samples import Sample

    tz = timezone(timedelta(hours=-7))
    samples = [
        Sample(datetime(2026, 6, 8, 18, m, tzinfo=tz), 1.8) for m in range(0, 30, 10)
    ]
    result = detect(samples, idle_w=1.8)

    assert result.anchors.watts_at_low is None
    assert any(CALIBRATION_DISTRUST in warning for warning in result.warnings)
