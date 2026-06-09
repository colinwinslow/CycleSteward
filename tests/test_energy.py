"""Idle subtraction and active-Wh integration (BDD Scenario B)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cyclesteward.energy import active_power_w, estimate_idle_power_w, integrate_active_wh
from cyclesteward.samples import Sample

TZ = timezone(timedelta(hours=-7))
_BASE = datetime(2026, 6, 8, 18, 0, 0, tzinfo=TZ)


def _sample(minute: int, power_w: float) -> Sample:
    return Sample(timestamp=_BASE + timedelta(minutes=minute), power_w=power_w)


def test_active_power_clamps_at_zero():
    assert active_power_w(10.0, 2.0) == 8.0
    assert active_power_w(1.5, 2.0) == 0.0  # below idle -> no active power


def test_standby_only_samples_add_no_energy():
    # Begins and ends with standby/idle readings; nothing above idle.
    samples = [_sample(0, 2.0), _sample(30, 2.0), _sample(60, 2.0)]
    assert integrate_active_wh(samples, idle_w=2.0) == 0.0


def test_integration_uses_idle_subtracted_power():
    # Two readings of 10 W, one hour apart, idle 2 W -> 8 W active for 1 h = 8 Wh.
    samples = [
        Sample(datetime(2026, 6, 8, 18, 0, tzinfo=TZ), 10.0),
        Sample(datetime(2026, 6, 8, 19, 0, tzinfo=TZ), 10.0),
    ]
    assert integrate_active_wh(samples, idle_w=2.0) == 8.0


def test_trapezoidal_ramp():
    # 0 W active rising to 8 W active over 1 h -> average 4 W -> 4 Wh.
    samples = [
        Sample(datetime(2026, 6, 8, 18, 0, tzinfo=TZ), 2.0),
        Sample(datetime(2026, 6, 8, 19, 0, tzinfo=TZ), 10.0),
    ]
    assert integrate_active_wh(samples, idle_w=2.0) == 4.0


def test_non_increasing_interval_is_skipped():
    samples = [
        Sample(datetime(2026, 6, 8, 19, 0, tzinfo=TZ), 10.0),
        Sample(datetime(2026, 6, 8, 18, 0, tzinfo=TZ), 10.0),  # goes backwards
    ]
    assert integrate_active_wh(samples, idle_w=2.0) == 0.0


def test_estimate_idle_is_lowest_reading():
    samples = [_sample(0, 1.8), _sample(10, 69.0), _sample(20, 84.0), _sample(30, 1.9)]
    assert estimate_idle_power_w(samples) == 1.8
