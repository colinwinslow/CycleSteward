"""Charge-session sample model and fixture/history parsing.

This module turns rows of ``timestamp,power_w[,temperature_c]`` into validated
``Sample`` objects. The same plain-row contract serves both CSV fixtures and
Home Assistant history exported into that shape (ADR-0010): the core never
imports Home Assistant; data always enters as plain rows.

A dedicated metering plug is assumed (ADR-0001), so ``power_w`` is the charger's
own wall power with no shared-circuit baseline to subtract.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .errors import FixtureError

REQUIRED_COLUMNS = ("timestamp", "power_w")

# Values that mean "no reading" rather than a number. A transient one of these
# (sensor restart, Zigbee hiccup) must not crash parsing; the row is skipped and
# a warning is recorded (robust-to-unknown handling, per the guardrails spec).
_MISSING_TOKENS = frozenset({"", "unknown", "unavailable", "none", "null", "nan"})


@dataclass(frozen=True)
class Sample:
    """One metered wall-power reading at a point in time."""

    timestamp: datetime
    power_w: float
    temperature_c: Optional[float] = None


@dataclass
class ParsedFixture:
    """Result of parsing: clean samples plus any non-fatal row warnings."""

    samples: List[Sample]
    warnings: List[str]


def _parse_timestamp(raw: str) -> datetime:
    text = raw.strip()
    # Tolerate a trailing 'Z' (UTC), which datetime.fromisoformat rejects on
    # older Pythons.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _parse_float(raw: str) -> float:
    return float(raw.strip())


def parse_rows(rows: Iterable[Dict[str, str]]) -> ParsedFixture:
    """Parse already-loaded dict rows (e.g. from a CSV reader or HA export).

    Rows with a missing/``unknown`` power or unparseable timestamp are skipped
    with a warning rather than aborting the whole session.
    """
    samples: List[Sample] = []
    warnings: List[str] = []
    for index, row in enumerate(rows):
        ts_raw = (row.get("timestamp") or "").strip()
        power_raw = (row.get("power_w") or "").strip()

        if power_raw.lower() in _MISSING_TOKENS or ts_raw.lower() in _MISSING_TOKENS:
            warnings.append(f"row {index}: skipped missing/unknown reading")
            continue
        try:
            timestamp = _parse_timestamp(ts_raw)
        except ValueError:
            warnings.append(f"row {index}: skipped unparseable timestamp {ts_raw!r}")
            continue
        try:
            power_w = _parse_float(power_raw)
        except ValueError:
            warnings.append(f"row {index}: skipped non-numeric power_w {power_raw!r}")
            continue

        temperature_c: Optional[float] = None
        temp_raw = (row.get("temperature_c") or "").strip()
        if temp_raw and temp_raw.lower() not in _MISSING_TOKENS:
            try:
                temperature_c = _parse_float(temp_raw)
            except ValueError:
                warnings.append(f"row {index}: ignored non-numeric temperature_c {temp_raw!r}")

        samples.append(Sample(timestamp=timestamp, power_w=power_w, temperature_c=temperature_c))

    return ParsedFixture(samples=samples, warnings=warnings)


def parse_csv(path: str | Path) -> ParsedFixture:
    """Parse a CSV charge-session fixture into samples.

    Raises ``FixtureError`` if a required column is absent (a structural problem
    that prevents any trustworthy summary).
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields: Sequence[str] = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fields]
        if missing:
            raise FixtureError(
                f"fixture {path.name} missing required column(s): {', '.join(missing)}"
            )
        rows = list(reader)
    return parse_rows(rows)
