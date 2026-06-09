"""Idle subtraction and active-energy integration.

Active wall Wh is the *calibration aid* (ADR-0002): integrate
``max(power_w - idle_w, 0)`` over time. It is not the runtime SoC metric, but it
is the cleanest way to measure a full session and locate where a target falls in
wattage terms.
"""

from __future__ import annotations

from typing import Sequence

from .samples import Sample


def estimate_idle_power_w(samples: Sequence[Sample]) -> float:
    """Estimate the charger's standby power as the lowest observed wall power.

    On a dedicated plug (ADR-0001) the floor of the curve is the charger's own
    idle draw. Callers may override with an explicit measured idle value.
    """
    if not samples:
        return 0.0
    return min(sample.power_w for sample in samples)


def active_power_w(power_w: float, idle_w: float) -> float:
    """Idle-subtracted, non-negative active power for one reading."""
    active = power_w - idle_w
    return active if active > 0.0 else 0.0


def integrate_active_wh(samples: Sequence[Sample], idle_w: float) -> float:
    """Trapezoidal integral of active power over time, in watt-hours.

    Intervals with a non-positive time delta (duplicate or out-of-order
    timestamps) are skipped; ordering problems are surfaced as warnings by the
    analyzer, not silently integrated.
    """
    total_wh = 0.0
    for first, second in zip(samples, samples[1:]):
        dt_hours = (second.timestamp - first.timestamp).total_seconds() / 3600.0
        if dt_hours <= 0.0:
            continue
        active_first = active_power_w(first.power_w, idle_w)
        active_second = active_power_w(second.power_w, idle_w)
        total_wh += 0.5 * (active_first + active_second) * dt_hours
    return total_wh
