"""Exception types for the CycleSteward core."""

from __future__ import annotations


class CycleStewardError(Exception):
    """Base class for all CycleSteward core errors."""


class FixtureError(CycleStewardError):
    """A charge-session fixture could not be parsed or is structurally invalid.

    Raised for problems that prevent producing any trustworthy summary at all,
    such as a missing required column. Per-row value problems (a single
    ``unknown`` reading) are not fatal; they are surfaced as warnings instead.
    """
