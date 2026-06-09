"""Real Swoop ASM charge session (derived from a Home Assistant export).

This is the first real-data exercise of the analyzer and the ADR-0010 import
path. It also documents two honest real-world findings the synthetic fixtures
do not show (see comments below).
"""

from __future__ import annotations

from cyclesteward.profile import analyze
from cyclesteward.samples import parse_csv


def test_real_session_parses_and_detects_transition(fixtures_dir):
    parsed = parse_csv(fixtures_dir / "real-swoop-asm-charge.csv")
    assert parsed.warnings == []
    assert len(parsed.samples) == 80

    summary = analyze(parsed.samples, profile_id="fixture:real-swoop-asm-charge")
    data = summary.to_dict()

    # Relay-off reads 0 W on this dedicated plug, so idle estimates to 0.
    assert data["idle_power_w"] == 0.0
    # The CC->CV peak is detected correctly.
    assert data["anchors"]["watts_at_transition"] == 83.9
    assert data["landmarks"]["peak_timestamp"].startswith("2026-06-05T13:26:29")
    assert data["landmarks"]["completion_timestamp"] is not None


def test_real_session_active_wh_matches_plug_energy_meter(fixtures_dir):
    # Independent validation: the plug's own cumulative energy meter rose
    # 75.96 - 75.38 = 0.58 kWh (~580 Wh) across the session. The trapezoidal
    # integration should land within a few percent of that.
    parsed = parse_csv(fixtures_dir / "real-swoop-asm-charge.csv")
    summary = analyze(parsed.samples, profile_id="x")
    assert 560.0 < summary.active_full_wh < 610.0


def test_real_session_watts_at_low_uses_settled_cc_value(fixtures_dir):
    # FIXED (F2): inrush settling now skips the rising ramp (~65.7 W) and latches
    # onto the first stable consecutive pair (~69.7 W).
    parsed = parse_csv(fixtures_dir / "real-swoop-asm-charge.csv")
    summary = analyze(parsed.samples, profile_id="x")

    assert 68.0 < summary.anchors.watts_at_low < 72.0


def test_real_session_mid_taper_cutoff_is_detected(fixtures_dir):
    # FIXED (G3): the session ends with a sharp relay cutoff mid-taper; the
    # taper_floor_w is None and TAPER_AMBIGUOUS is in warnings.
    from cyclesteward.landmarks import TAPER_AMBIGUOUS

    parsed = parse_csv(fixtures_dir / "real-swoop-asm-charge.csv")
    summary = analyze(parsed.samples, profile_id="x")

    assert summary.anchors.taper_floor_w is None
    assert any(TAPER_AMBIGUOUS in w for w in summary.warnings)
