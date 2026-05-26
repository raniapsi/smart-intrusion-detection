"""
Badge event generator.

A pure function: given the context (who, where, when, what outcome),
returns a UnifiedEvent. State is held by the caller (user_day.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from schemas import (
    AccessResult,
    BadgeAccessPayload,
    EventType,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
)


def make_badge_event(
    *,
    timestamp: datetime,
    building_id: str,
    zone_id: str,
    reader_device_id: str,
    badge_id: str,
    user_id: Optional[str],
    access_result: AccessResult = AccessResult.GRANTED,
    door_id: Optional[str] = None,
) -> UnifiedEvent:
    """
    Build a single BADGE_ACCESS event.

    `user_id` is None when the badge is not registered to any user
    (e.g. revoked badge attempt) -- the schema permits this.
    """
    severity = (
        SeverityRaw.WARNING
        if access_result != AccessResult.GRANTED
        else SeverityRaw.INFO
    )
    return UnifiedEvent(
        event_type=EventType.BADGE_ACCESS,
        source_layer=SourceLayer.PHYSICAL,
        timestamp=timestamp,
        building_id=building_id,
        zone_id=zone_id,
        device_id=reader_device_id,
        user_id=user_id,
        severity_raw=severity,
        payload=BadgeAccessPayload(
            badge_id=badge_id,
            reader_device_id=reader_device_id,
            access_result=access_result,
            door_id=door_id,
        ),
    )
