"""
Temporal features.

Pure functions: each takes the event and the user profile (if known)
and returns the feature value(s). No state.
"""

from __future__ import annotations

import math
from typing import Optional

from schemas import UnifiedEvent, UserProfile


def hour_sin_cos(event: UnifiedEvent) -> tuple[float, float]:
    """
    Cyclic encoding of hour-of-day. Avoids the discontinuity at midnight
    that a raw integer would create (hour=23 and hour=0 are 23 apart in
    integer space but they're temporally adjacent).
    """
    seconds = (
        event.timestamp.hour * 3600
        + event.timestamp.minute * 60
        + event.timestamp.second
    )
    angle = 2.0 * math.pi * seconds / 86400.0
    return math.sin(angle), math.cos(angle)


def day_of_week(event: UnifiedEvent) -> int:
    """0 = Monday, 6 = Sunday."""
    return event.timestamp.weekday()


def is_weekend(event: UnifiedEvent) -> int:
    return 1 if event.timestamp.weekday() >= 5 else 0


def is_within_typical_hours(
    event: UnifiedEvent, user: Optional[UserProfile]
) -> int:
    """
    1 if the event time is between the user's typical_arrival and
    typical_departure (inclusive). 0 otherwise. Returns 0 also when the
    event has no associated user (network flows, motion, etc.).
    """
    if user is None:
        return 0
    t = event.timestamp.time()
    arrival = user.typical_arrival
    departure = user.typical_departure
    if arrival <= departure:
        return 1 if (arrival <= t <= departure) else 0
    # Overnight shift case (typical_arrival > typical_departure). Not used in
    # our 8-18 baseline but kept correct in case we add shifts later.
    return 1 if (t >= arrival or t <= departure) else 0


def minutes_off_typical_midshift(
    event: UnifiedEvent, user: Optional[UserProfile]
) -> float:
    """
    Signed minutes from the midpoint of the user's typical working window.
    Negative = before, positive = after.

    Returns NaN when no user is associated (the IF will treat it as missing
    and the model knows to ignore).
    """
    if user is None:
        return float("nan")

    arrival_s = (
        user.typical_arrival.hour * 60 + user.typical_arrival.minute
    )
    departure_s = (
        user.typical_departure.hour * 60 + user.typical_departure.minute
    )
    midpoint_min = (arrival_s + departure_s) / 2.0

    event_min = (
        event.timestamp.hour * 60 + event.timestamp.minute
    )
    return float(event_min - midpoint_min)