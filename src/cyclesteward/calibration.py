"""Calibration profile model.

A ``CalibrationProfile`` accumulates charge-session observations and derives the
two wattage anchors, taper floor, and active-Wh denominator that power the
runtime SoC estimator (ADR-0002).  User-supplied SoC reports are stored as
coarse intervals, never collapsed to exact percentages (invariant #6).  Partial
observations refine ranges but never overwrite a high-confidence full
calibration (spec §"Profile updates").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .landmarks import CALIBRATION_DISTRUST, TAPER_AMBIGUOUS
from .profile import ProfileSummary

SCHEMA_VERSION = 1

_WATT_DP = 3
_WH_DP = 4
_RATIO_DP = 4


class ProfileState(str, Enum):
    UNCALIBRATED = "uncalibrated"
    CALIBRATING = "calibrating"
    CALIBRATED = "calibrated"
    STALE = "stale"
    FAULTED = "faulted"


@dataclass
class SocReport:
    """A user-supplied SoC report stored as a coarse interval, never a point."""

    label: str
    interval_low_pct: Optional[float]
    interval_high_pct: Optional[float]
    coarse: bool = True

    @classmethod
    def from_dots(cls, dot_count: int, dot_max: int) -> SocReport:
        """Build a coarse SoC report from a dot-count display (e.g. 0 of 5)."""
        low = dot_count / dot_max * 100.0
        high = (dot_count + 1) / dot_max * 100.0
        return cls(
            label=f"{dot_count} of {dot_max} dots",
            interval_low_pct=low,
            interval_high_pct=high,
            coarse=True,
        )

    @classmethod
    def display_empty(cls) -> SocReport:
        """The display-empty anchor: motor-cutoff / 0 dots, not true 0% SoC."""
        return cls(
            label="display_empty",
            interval_low_pct=0.0,
            interval_high_pct=15.0,
            coarse=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "interval_low_pct": self.interval_low_pct,
            "interval_high_pct": self.interval_high_pct,
            "coarse": self.coarse,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SocReport:
        return cls(
            label=d["label"],
            interval_low_pct=d.get("interval_low_pct"),
            interval_high_pct=d.get("interval_high_pct"),
            coarse=d.get("coarse", True),
        )


@dataclass
class SocAssumptions:
    """Assumed SoC values at the two wattage anchors.

    These are engineering assumptions, not measured BMS values (ADR-0002).
    """

    soc_at_low_pct: float = 0.0
    soc_at_transition_pct: float = 80.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "soc_at_low_pct": self.soc_at_low_pct,
            "soc_at_transition_pct": self.soc_at_transition_pct,
            "note": "assumed; not measured BMS values",
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SocAssumptions:
        return cls(
            soc_at_low_pct=d.get("soc_at_low_pct", 0.0),
            soc_at_transition_pct=d.get("soc_at_transition_pct", 80.0),
        )


@dataclass
class WattageAnchor:
    """One wattage anchor with its assumed SoC label and confidence."""

    watts: float
    assumed_soc_label: str
    confidence: str = "high"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "watts": round(self.watts, _WATT_DP),
            "assumed_soc_label": self.assumed_soc_label,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> WattageAnchor:
        return cls(
            watts=d["watts"],
            assumed_soc_label=d["assumed_soc_label"],
            confidence=d.get("confidence", "high"),
        )


@dataclass
class OverheadEstimate:
    """Combined charger efficiency + unused low-end reserve ratio.

    ``ratio = measured_active_full_wh / rated_capacity_wh``.  Confidence is
    always "low" because rated capacity is a nominal value.
    """

    ratio: float
    rated_capacity_wh: float
    measured_full_wh: float
    confidence: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ratio": round(self.ratio, _RATIO_DP),
            "rated_capacity_wh": round(self.rated_capacity_wh, _WH_DP),
            "measured_full_wh": round(self.measured_full_wh, _WH_DP),
            "confidence": self.confidence,
            "note": "nominal rated capacity; derived overhead carries uncertainty",
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> OverheadEstimate:
        return cls(
            ratio=d["ratio"],
            rated_capacity_wh=d["rated_capacity_wh"],
            measured_full_wh=d["measured_full_wh"],
            confidence=d.get("confidence", "low"),
        )


@dataclass
class FullObservation:
    """One full-session observation stored inside the profile."""

    timestamp: datetime
    active_wh: float
    watts_at_low: Optional[float]
    watts_at_transition: Optional[float]
    trusted: bool
    soc_at_start: Optional[SocReport] = None
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "active_wh": round(self.active_wh, _WH_DP),
            "watts_at_low": (
                None if self.watts_at_low is None else round(self.watts_at_low, _WATT_DP)
            ),
            "watts_at_transition": (
                None
                if self.watts_at_transition is None
                else round(self.watts_at_transition, _WATT_DP)
            ),
            "trusted": self.trusted,
            "soc_at_start": self.soc_at_start.to_dict() if self.soc_at_start else None,
            "quality_flags": list(self.quality_flags),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FullObservation:
        return cls(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            active_wh=d["active_wh"],
            watts_at_low=d.get("watts_at_low"),
            watts_at_transition=d.get("watts_at_transition"),
            trusted=d.get("trusted", True),
            soc_at_start=SocReport.from_dict(d["soc_at_start"]) if d.get("soc_at_start") else None,
            quality_flags=d.get("quality_flags", []),
        )


@dataclass
class PartialObservation:
    """One partial-session observation (does not anchor the full Wh denominator)."""

    timestamp: datetime
    active_wh: float
    soc_at_start: Optional[SocReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "active_wh": round(self.active_wh, _WH_DP),
            "soc_at_start": self.soc_at_start.to_dict() if self.soc_at_start else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PartialObservation:
        return cls(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            active_wh=d["active_wh"],
            soc_at_start=SocReport.from_dict(d["soc_at_start"]) if d.get("soc_at_start") else None,
        )


@dataclass
class TemperatureObservation:
    """One opportunistic full-span datapoint, carrying temperature for later compensation fitting."""

    timestamp: datetime
    active_wh: float
    watts_at_low: Optional[float]
    temperature_c: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "active_wh": round(self.active_wh, _WH_DP),
            "watts_at_low": (
                None if self.watts_at_low is None else round(self.watts_at_low, _WATT_DP)
            ),
            "temperature_c": self.temperature_c,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TemperatureObservation:
        return cls(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            active_wh=d["active_wh"],
            watts_at_low=d.get("watts_at_low"),
            temperature_c=d.get("temperature_c"),
        )


@dataclass
class CalibrationProfile:
    """The persisted calibration profile for one charger/battery/meter triple.

    State machine:
      UNCALIBRATED → (bad session) → CALIBRATING
      UNCALIBRATED → (trusted full session) → CALIBRATED
      CALIBRATING  → (trusted full session) → CALIBRATED
    """

    charger_label: str
    battery_label: str
    meter_id: str
    rated_capacity_wh: Optional[float] = None

    state: ProfileState = ProfileState.UNCALIBRATED

    idle_power_w: Optional[float] = None
    watts_at_low: Optional[WattageAnchor] = None
    watts_at_transition: Optional[WattageAnchor] = None
    taper_floor_w: Optional[float] = None
    active_full_wh: Optional[float] = None

    overhead: Optional[OverheadEstimate] = None
    assumptions: Optional[SocAssumptions] = None

    full_observations: List[FullObservation] = field(default_factory=list)
    partial_observations: List[PartialObservation] = field(default_factory=list)
    temperature_observations: List[TemperatureObservation] = field(default_factory=list)
    soc_reports: List[SocReport] = field(default_factory=list)

    warnings: List[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def ingest_full_session(
        self,
        summary: ProfileSummary,
        *,
        soc_at_start: Optional[SocReport] = None,
        assumptions: Optional[SocAssumptions] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Ingest a full (display-empty to completion) charge session."""
        if timestamp is None:
            timestamp = datetime.now()
        if assumptions is None:
            assumptions = SocAssumptions()

        is_trusted = not any(CALIBRATION_DISTRUST in w for w in summary.warnings)
        quality_flags = [w for w in summary.warnings if CALIBRATION_DISTRUST in w]

        obs = FullObservation(
            timestamp=timestamp,
            active_wh=summary.active_full_wh,
            watts_at_low=summary.anchors.watts_at_low,
            watts_at_transition=summary.anchors.watts_at_transition,
            trusted=is_trusted,
            soc_at_start=soc_at_start,
            quality_flags=quality_flags,
        )
        self.full_observations.append(obs)

        if soc_at_start is not None:
            self.soc_reports.append(soc_at_start)

        if not is_trusted:
            for flag in quality_flags:
                self.warnings.append(f"session not trusted for calibration: {flag}")
            if self.state == ProfileState.UNCALIBRATED:
                self.state = ProfileState.CALIBRATING
            return

        self.idle_power_w = summary.idle_power_w
        if summary.anchors.watts_at_low is not None:
            self.watts_at_low = WattageAnchor(
                watts=summary.anchors.watts_at_low,
                assumed_soc_label="display_empty",
                confidence="high",
            )
        if summary.anchors.watts_at_transition is not None:
            self.watts_at_transition = WattageAnchor(
                watts=summary.anchors.watts_at_transition,
                assumed_soc_label="cc_cv_transition",
                confidence="high",
            )
        self.taper_floor_w = summary.anchors.taper_floor_w
        self.active_full_wh = summary.active_full_wh
        self.assumptions = assumptions

        if self.rated_capacity_wh is not None:
            self.overhead = OverheadEstimate(
                ratio=summary.active_full_wh / self.rated_capacity_wh,
                rated_capacity_wh=self.rated_capacity_wh,
                measured_full_wh=summary.active_full_wh,
                confidence="low",
            )

        self.state = ProfileState.CALIBRATED

    def ingest_partial_session(
        self,
        summary: ProfileSummary,
        *,
        soc_at_start: Optional[SocReport] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record a partial session.  Never overwrites the full active-Wh denominator."""
        if timestamp is None:
            timestamp = datetime.now()

        obs = PartialObservation(
            timestamp=timestamp,
            active_wh=summary.active_full_wh,
            soc_at_start=soc_at_start,
        )
        self.partial_observations.append(obs)

        if soc_at_start is not None:
            self.soc_reports.append(soc_at_start)

    def classify_opportunistic_session(
        self,
        summary: ProfileSummary,
        *,
        temperature_c: Optional[float] = None,
        timestamp: Optional[datetime] = None,
        proximity_frac: float = 0.10,
    ) -> tuple[bool, str]:
        """Classify a completed session as an opportunistic full-span datapoint.

        Returns ``(promoted, reason)``.  Promotion requires:
        - Profile is already calibrated with a known ``watts_at_low`` anchor.
        - Session has no ``CALIBRATION_DISTRUST`` or ``TAPER_AMBIGUOUS`` warnings.
        - Session's ``watts_at_low`` is within ``proximity_frac`` of the profile anchor.

        When promoted the ``(temperature_c, active_wh)`` pair is stored for later
        temperature/full-Wh compensation fitting (ADR-0008).
        """
        if self.watts_at_low is None:
            return False, "profile not yet calibrated; cannot classify opportunistic session"

        if any(CALIBRATION_DISTRUST in w for w in summary.warnings):
            return False, "session not trusted for calibration; not promoted"

        if any(TAPER_AMBIGUOUS in w for w in summary.warnings):
            return False, "taper floor ambiguous (likely relay cutoff); not promoted"

        if summary.anchors.watts_at_low is None:
            return False, "session has no detected CC-start wattage; not promoted"

        anchor_w = self.watts_at_low.watts
        session_w = summary.anchors.watts_at_low
        if abs(session_w - anchor_w) / anchor_w > proximity_frac:
            pct = abs(session_w - anchor_w) / anchor_w * 100
            return (
                False,
                f"start wattage {session_w:.1f} W is {pct:.0f}% from learned anchor "
                f"{anchor_w:.1f} W (>{proximity_frac:.0%} tolerance); not promoted",
            )

        if timestamp is None:
            timestamp = datetime.now()

        obs = TemperatureObservation(
            timestamp=timestamp,
            active_wh=summary.active_full_wh,
            watts_at_low=summary.anchors.watts_at_low,
            temperature_c=temperature_c,
        )
        self.temperature_observations.append(obs)
        return True, "opportunistic full-span datapoint"

    def target_wattage(
        self,
        target_soc_pct: float,
        assumptions: Optional[SocAssumptions] = None,
    ) -> Optional[float]:
        """Wattage along the CC ramp that corresponds to ``target_soc_pct``.

        Returns ``None`` if the profile has not yet been calibrated.  Linear
        interpolation between the two wattage anchors using the stored (or
        caller-supplied) SoC assumptions.
        """
        if self.watts_at_low is None or self.watts_at_transition is None:
            return None

        asm = assumptions or self.assumptions or SocAssumptions()
        soc_span = asm.soc_at_transition_pct - asm.soc_at_low_pct
        if soc_span <= 0:
            return None

        watt_span = self.watts_at_transition.watts - self.watts_at_low.watts
        t = (target_soc_pct - asm.soc_at_low_pct) / soc_span
        return self.watts_at_low.watts + t * watt_span

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "charger_label": self.charger_label,
            "battery_label": self.battery_label,
            "meter_id": self.meter_id,
            "rated_capacity_wh": self.rated_capacity_wh,
            "state": self.state.value,
            "idle_power_w": (
                None if self.idle_power_w is None else round(self.idle_power_w, _WATT_DP)
            ),
            "watts_at_low": self.watts_at_low.to_dict() if self.watts_at_low else None,
            "watts_at_transition": (
                self.watts_at_transition.to_dict() if self.watts_at_transition else None
            ),
            "taper_floor_w": (
                None if self.taper_floor_w is None else round(self.taper_floor_w, _WATT_DP)
            ),
            "active_full_wh": (
                None if self.active_full_wh is None else round(self.active_full_wh, _WH_DP)
            ),
            "overhead": self.overhead.to_dict() if self.overhead else None,
            "assumptions": self.assumptions.to_dict() if self.assumptions else None,
            "full_observations": [obs.to_dict() for obs in self.full_observations],
            "partial_observations": [obs.to_dict() for obs in self.partial_observations],
            "temperature_observations": [obs.to_dict() for obs in self.temperature_observations],
            "soc_reports": [r.to_dict() for r in self.soc_reports],
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CalibrationProfile:
        profile = cls(
            charger_label=d["charger_label"],
            battery_label=d["battery_label"],
            meter_id=d["meter_id"],
            rated_capacity_wh=d.get("rated_capacity_wh"),
        )
        profile.state = ProfileState(d.get("state", ProfileState.UNCALIBRATED.value))
        profile.idle_power_w = d.get("idle_power_w")
        profile.watts_at_low = (
            WattageAnchor.from_dict(d["watts_at_low"]) if d.get("watts_at_low") else None
        )
        profile.watts_at_transition = (
            WattageAnchor.from_dict(d["watts_at_transition"])
            if d.get("watts_at_transition")
            else None
        )
        profile.taper_floor_w = d.get("taper_floor_w")
        profile.active_full_wh = d.get("active_full_wh")
        profile.overhead = (
            OverheadEstimate.from_dict(d["overhead"]) if d.get("overhead") else None
        )
        profile.assumptions = (
            SocAssumptions.from_dict(d["assumptions"]) if d.get("assumptions") else None
        )
        profile.full_observations = [
            FullObservation.from_dict(o) for o in d.get("full_observations", [])
        ]
        profile.partial_observations = [
            PartialObservation.from_dict(o) for o in d.get("partial_observations", [])
        ]
        profile.temperature_observations = [
            TemperatureObservation.from_dict(o) for o in d.get("temperature_observations", [])
        ]
        profile.soc_reports = [SocReport.from_dict(r) for r in d.get("soc_reports", [])]
        profile.warnings = list(d.get("warnings", []))
        profile.schema_version = d.get("schema_version", SCHEMA_VERSION)
        return profile

    @classmethod
    def from_json(cls, json_str: str) -> CalibrationProfile:
        return cls.from_dict(json.loads(json_str))
