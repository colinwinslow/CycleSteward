"""Profile summary model and the top-level analyze() entry point.

``analyze`` turns parsed samples into a deterministic, inspectable
``ProfileSummary`` whose JSON form is the anchor artifact for this project's
first slice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .energy import estimate_idle_power_w, integrate_active_wh
from .landmarks import Anchors, Landmarks, detect
from .samples import Sample

SCHEMA_VERSION = 1

# Rounding keeps the JSON artifact byte-stable for a given fixture.
_WATT_DP = 3
_WH_DP = 4


def _round_opt(value: Optional[float], places: int) -> Optional[float]:
    return None if value is None else round(value, places)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


@dataclass
class ProfileSummary:
    profile_id: str
    sample_count: int
    idle_power_w: float
    anchors: Anchors
    active_full_wh: float
    landmarks: Landmarks
    warnings: List[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "sample_count": self.sample_count,
            "idle_power_w": round(self.idle_power_w, _WATT_DP),
            "anchors": {
                "watts_at_low": _round_opt(self.anchors.watts_at_low, _WATT_DP),
                "watts_at_transition": _round_opt(self.anchors.watts_at_transition, _WATT_DP),
                "taper_floor_w": _round_opt(self.anchors.taper_floor_w, _WATT_DP),
            },
            "active_full_wh": round(self.active_full_wh, _WH_DP),
            "landmarks": {
                "active_start_timestamp": _iso(self.landmarks.active_start_timestamp),
                "peak_power_w": _round_opt(self.landmarks.peak_power_w, _WATT_DP),
                "peak_timestamp": _iso(self.landmarks.peak_timestamp),
                "taper_start_timestamp": _iso(self.landmarks.taper_start_timestamp),
                "completion_timestamp": _iso(self.landmarks.completion_timestamp),
            },
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def analyze(
    samples: Sequence[Sample],
    *,
    profile_id: str,
    idle_power_w: Optional[float] = None,
    input_warnings: Sequence[str] = (),
) -> ProfileSummary:
    """Build a profile summary from samples.

    ``idle_power_w`` may be supplied (a measured standby value); otherwise it is
    estimated as the lowest observed wall power. ``input_warnings`` carries any
    non-fatal warnings raised during parsing (e.g. skipped ``unknown`` rows).
    """
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    idle = estimate_idle_power_w(ordered) if idle_power_w is None else idle_power_w

    detection = detect(ordered, idle)
    active_full_wh = integrate_active_wh(ordered, idle)

    warnings: List[str] = list(input_warnings) + list(detection.warnings)

    return ProfileSummary(
        profile_id=profile_id,
        sample_count=len(ordered),
        idle_power_w=idle,
        anchors=detection.anchors,
        active_full_wh=active_full_wh,
        landmarks=detection.landmarks,
        warnings=warnings,
    )
