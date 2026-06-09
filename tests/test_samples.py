"""Parsing and validation of charge-session fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cyclesteward.errors import FixtureError
from cyclesteward.samples import parse_csv, parse_rows


def test_parse_valid_csv_yields_samples(clean_fixture):
    parsed = parse_csv(clean_fixture)

    assert len(parsed.samples) == 49
    assert parsed.warnings == []
    first = parsed.samples[0]
    assert first.power_w == 1.80
    assert first.temperature_c == 21.0
    assert first.timestamp == datetime(
        2026, 6, 8, 18, 0, 0, tzinfo=timezone(timedelta(hours=-7))
    )


def test_missing_required_column_raises(fixtures_dir):
    with pytest.raises(FixtureError) as excinfo:
        parse_csv(fixtures_dir / "malformed-missing-power.csv")
    assert "power_w" in str(excinfo.value)


def test_midnight_rollover_timestamps_parse(clean_fixture):
    parsed = parse_csv(clean_fixture)
    # The session crosses midnight; the last sample is on the next day.
    assert parsed.samples[-1].timestamp == datetime(
        2026, 6, 9, 2, 0, 0, tzinfo=timezone(timedelta(hours=-7))
    )


def test_unknown_and_empty_rows_are_skipped_with_warnings():
    rows = [
        {"timestamp": "2026-06-08T18:00:00-07:00", "power_w": "1.8"},
        {"timestamp": "2026-06-08T18:10:00-07:00", "power_w": "unknown"},
        {"timestamp": "2026-06-08T18:20:00-07:00", "power_w": ""},
        {"timestamp": "2026-06-08T18:30:00-07:00", "power_w": "70.0"},
        {"timestamp": "bogus", "power_w": "71.0"},
    ]
    parsed = parse_rows(rows)

    assert [s.power_w for s in parsed.samples] == [1.8, 70.0]
    assert len(parsed.warnings) == 3  # unknown, empty, unparseable timestamp


def test_trailing_z_timestamp_is_accepted():
    parsed = parse_rows([{"timestamp": "2026-06-08T18:00:00Z", "power_w": "5"}])
    assert parsed.samples[0].timestamp.utcoffset() == timedelta(0)
