"""
Spatial features.

Computes features that depend on the zone where the event happens and
on the user's typical zones.
"""

from __future__ import annotations

from typing import Optional

from schemas import UnifiedEvent, UserProfile, Zone, ZoneSensitivity


_SENSITIVITY_LEVEL: dict[ZoneSensitivity, int] = {
    ZoneSensitivity.PUBLIC: 0,
    ZoneSensitivity.STANDARD: 1,
    ZoneSensitivity.RESTRICTED: 2,
    ZoneSensitivity.CRITICAL: 3,
}


def zone_sensitivity_lvl(zone: Optional[Zone]) -> int:
    """
    Numeric encoding of the zone's sensitivity tier.
    Returns 1 (STANDARD) as a neutral default if zone is unknown.
    """
    if zone is None:
        return 1
    return _SENSITIVITY_LEVEL[zone.sensitivity]


def is_typical_zone_for_user(
    event: UnifiedEvent, user: Optional[UserProfile]
) -> int:
    """
    1 if the event's zone is in the user's typical_zones list, 0 if not.
    -1 if the event has no associated user (so the IF can distinguish
    "no user" from "user but not their zone").
    """
    if user is None:
        return -1
    return 1 if event.zone_id in user.typical_zones else 0