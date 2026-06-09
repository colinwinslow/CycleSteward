"""Curve-landmark and wattage-anchor detection.

Detects the CC/CV-like shape features of a charge session and the two wattage
anchors that define the SoC model (ADR-0002):

- ``watts_at_low``       - CC-start wall wattage (the low anchor)
- ``watts_at_transition``- wall wattage at the CC->CV peak (the transition anchor)
- ``taper_floor_w``      - settled near-idle wattage during CV, before completion

All thresholds are expressed as fractions of *this session's own* peak active
power, never as universal watt values (invariant #5): a fixed watt threshold
would not transfer across chargers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence

from .energy import active_power_w
from .samples import Sample

# Curve-relative detection fractions (of the session's own peak active power).
ACTIVE_ONSET_FRAC = 0.5  # CC-start: first reading at >= 50% of peak active power
TAPER_CONFIRM_FRAC = 0.95  # taper begins once power has dropped >5% below the peak
COMPLETION_FRAC = 0.05  # completion: active power falls back below 5% of peak

# Inrush settling: scan forward from onset until consecutive readings are within
# this fraction of each other.  Catches chargers that ramp to CC over several
# samples before settling.
INRUSH_STABLE_FRAC = 0.05

# If the apparent taper floor is still above this fraction of peak active power,
# the session likely ended via a relay cutoff rather than a natural CV taper.
TAPER_FLOOR_MAX_ACTIVE_FRAC = 0.35

# A gap larger than this multiple of the median sampling interval looks like an
# interruption rather than normal sampling.
INTERRUPTION_GAP_MULTIPLE = 3.0

CALIBRATION_DISTRUST = "profile should not be trusted for calibration"
TAPER_AMBIGUOUS = "taper_floor_w is unreliable due to apparent relay cutoff"


@dataclass
class Landmarks:
    active_start_timestamp: Optional[datetime] = None
    peak_power_w: Optional[float] = None
    peak_timestamp: Optional[datetime] = None
    taper_start_timestamp: Optional[datetime] = None
    completion_timestamp: Optional[datetime] = None


@dataclass
class Anchors:
    watts_at_low: Optional[float] = None
    watts_at_transition: Optional[float] = None
    taper_floor_w: Optional[float] = None


@dataclass
class Detection:
    landmarks: Landmarks
    anchors: Anchors
    warnings: List[str]


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2 == 1:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _monotonicity_warnings(samples: Sequence[Sample]) -> List[str]:
    warnings: List[str] = []
    out_of_order = any(
        second.timestamp <= first.timestamp for first, second in zip(samples, samples[1:])
    )
    if out_of_order:
        warnings.append(f"timestamps are not strictly increasing; {CALIBRATION_DISTRUST}")

    deltas = [
        (second.timestamp - first.timestamp).total_seconds()
        for first, second in zip(samples, samples[1:])
        if (second.timestamp - first.timestamp).total_seconds() > 0
    ]
    median_dt = _median(deltas)
    if median_dt > 0:
        biggest = max(deltas)
        if biggest > INTERRUPTION_GAP_MULTIPLE * median_dt:
            warnings.append(
                f"sampling gap of {biggest:.0f}s exceeds {INTERRUPTION_GAP_MULTIPLE:g}x the "
                f"median interval; session looks interrupted; {CALIBRATION_DISTRUST}"
            )
    return warnings


def detect(samples: Sequence[Sample], idle_w: float) -> Detection:
    """Detect landmarks, wattage anchors, and abnormal-shape warnings."""
    landmarks = Landmarks()
    anchors = Anchors()
    warnings: List[str] = []

    if len(samples) < 2:
        warnings.append(f"too few samples to detect a charge curve; {CALIBRATION_DISTRUST}")
        return Detection(landmarks=landmarks, anchors=anchors, warnings=warnings)

    warnings.extend(_monotonicity_warnings(samples))

    actives = [active_power_w(sample.power_w, idle_w) for sample in samples]
    peak_active = max(actives)
    if peak_active <= 0.0:
        warnings.append(f"no active charging detected above idle; {CALIBRATION_DISTRUST}")
        return Detection(landmarks=landmarks, anchors=anchors, warnings=warnings)

    peak_index = actives.index(peak_active)
    landmarks.peak_power_w = samples[peak_index].power_w
    landmarks.peak_timestamp = samples[peak_index].timestamp
    anchors.watts_at_transition = samples[peak_index].power_w

    # CC-start (low anchor): find onset then settle past any inrush ramp.
    onset_level = ACTIVE_ONSET_FRAC * peak_active
    onset_index: Optional[int] = None
    for index, active in enumerate(actives):
        if active >= onset_level:
            onset_index = index
            break

    if onset_index is not None:
        # Scan forward from onset until consecutive readings are within
        # INRUSH_STABLE_FRAC of each other.  This skips the rising edge of an
        # inrush ramp and lands on the settled CC wattage.
        settled_index = onset_index
        for scan in range(onset_index, min(peak_index, len(samples) - 1)):
            w_curr = samples[scan].power_w
            w_next = samples[scan + 1].power_w
            if w_curr > 0 and abs(w_next - w_curr) / w_curr < INRUSH_STABLE_FRAC:
                settled_index = scan
                break
        landmarks.active_start_timestamp = samples[settled_index].timestamp
        anchors.watts_at_low = samples[settled_index].power_w

    # Taper start: first reading after the peak that has dropped clearly below it.
    taper_confirm_level = TAPER_CONFIRM_FRAC * peak_active
    taper_index: Optional[int] = None
    for index in range(peak_index + 1, len(samples)):
        if actives[index] <= taper_confirm_level:
            taper_index = index
            landmarks.taper_start_timestamp = samples[index].timestamp
            break

    # Completion: first reading after the peak that falls back near idle.
    completion_level = COMPLETION_FRAC * peak_active
    completion_index: Optional[int] = None
    for index in range(peak_index + 1, len(samples)):
        if actives[index] <= completion_level:
            completion_index = index
            landmarks.completion_timestamp = samples[index].timestamp
            break

    # Taper floor: lowest wall wattage during taper, before completion.
    # Guard against relay cutoffs: if the apparent floor is still well above
    # idle (> TAPER_FLOOR_MAX_ACTIVE_FRAC of peak), the session was cut off
    # mid-taper and the value is an artefact, not a settled floor.
    if taper_index is not None:
        end = completion_index if completion_index is not None else len(samples)
        if end > taper_index:
            candidate_floor_w = min(sample.power_w for sample in samples[taper_index:end])
            candidate_active = max(candidate_floor_w - idle_w, 0.0)
            if candidate_active / peak_active > TAPER_FLOOR_MAX_ACTIVE_FRAC:
                warnings.append(
                    f"taper floor candidate ({candidate_floor_w:.1f} W) is "
                    f"{candidate_active / peak_active:.0%} of peak; "
                    f"{TAPER_AMBIGUOUS}"
                )
            else:
                anchors.taper_floor_w = candidate_floor_w

    if completion_index is None:
        warnings.append(
            f"charge never returned near idle; no completion detected; {CALIBRATION_DISTRUST}"
        )

    return Detection(landmarks=landmarks, anchors=anchors, warnings=warnings)
