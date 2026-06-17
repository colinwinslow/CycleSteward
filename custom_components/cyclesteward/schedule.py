"""Pure scheduling helpers for the HA adapter.

The next-occurrence rule (spec D3) lives here as a pure stdlib function so it can
be tested without a Home Assistant runtime.  Home Assistant code supplies the
``now`` argument from ``homeassistant.util.dt`` (the single timezone authority);
this helper never reads the clock or invents a timezone itself.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def next_occurrence(tod: time, now: datetime) -> datetime:
    """Return the next datetime matching ``tod``, at or after ``now``'s day.

    The result is anchored to ``now``'s date with the time-of-day ``tod``.  If
    that moment is already at or before ``now`` (the time-of-day has passed
    today), it rolls forward to tomorrow.  The result inherits ``now``'s
    ``tzinfo``, so passing an aware ``now`` yields an aware datetime — callers
    in HA pass ``dt_util.now()`` so the result is aware in HA's configured zone.

    ``tod`` sub-second precision is dropped; ``now`` must be tz-aware for the
    result to be aware.
    """
    candidate = now.replace(
        hour=tod.hour, minute=tod.minute, second=tod.second, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
