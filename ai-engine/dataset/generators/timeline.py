"""
Time helpers for the dataset generators.

All timestamps in the dataset are timezone-aware UTC, as required by the
schemas (UnifiedEvent rejects naive datetimes). A user's "9:00 arrival"
is interpreted as 9:00 UTC for simplicity — we are not modelling a
real building in a real timezone, just a self-consistent simulation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


UTC = timezone.utc


def combine_utc(d: date, t: time) -> datetime:
    """Combine a date and a time into a tz-aware UTC datetime."""
    return datetime.combine(d, t, tzinfo=UTC)


def at_offset(base: datetime, seconds: float) -> datetime:
    """Return base + seconds (float seconds, sub-second supported)."""
    return base + timedelta(seconds=seconds)


def time_of_day_seconds(t: time) -> float:
    """Convert a time (no date) into seconds-since-midnight."""
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000


def seconds_to_time(s: float) -> time:
    """Convert seconds-since-midnight back to a time (clamped to [0, 86399.999...])."""
    s = max(0.0, min(s, 86399.999_999))
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    micro = int((s - int(s)) * 1_000_000)
    return time(h, m, sec, micro)


def is_weekend(d: date) -> bool:
    """Saturday or Sunday."""
    return d.weekday() >= 5
