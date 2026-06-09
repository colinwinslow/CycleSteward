"""CycleSteward pure core.

A charger/battery wall-power model that runs without Home Assistant (ADR-0006).
The first slice is a fixture analyzer that turns a charge-session CSV (or
exported Home Assistant history) into a deterministic profile-summary JSON
carrying the wattage anchors (ADR-0002), the calibration active Wh, and curve
landmarks.
"""

from __future__ import annotations

from .errors import CycleStewardError, FixtureError
from .landmarks import Anchors, Detection, Landmarks, detect
from .profile import ProfileSummary, analyze
from .samples import ParsedFixture, Sample, parse_csv, parse_rows

__version__ = "0.0.0"

__all__ = [
    "CycleStewardError",
    "FixtureError",
    "Sample",
    "ParsedFixture",
    "parse_csv",
    "parse_rows",
    "Anchors",
    "Landmarks",
    "Detection",
    "detect",
    "ProfileSummary",
    "analyze",
    "__version__",
]
