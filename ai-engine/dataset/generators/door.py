"""
Door event generators (opened, closed, forced).

In a normal access pattern, a door produces TWO events:
  - DOOR_OPENED right after a granted badge access
  - DOOR_CLOSED a few seconds later

A FORCED door is generated only by attack scenarios (step 2c).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from schemas import (
    DoorClosedPayload,
    DoorForcedPayload,
    DoorOpenedPayload,
    EventType,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
)


def make_door_opened_event(
    *,
    timestamp: datetime,
    building_id: str,
    zone_id: str,
    sensor_device_id: str,
    door_id: str,
    associated_badge_event_id: Optional[UUID] = None,
) -> UnifiedEvent:
    """Door OPEN event, normally paired with a preceding badge event."""
    return UnifiedEvent(
        event_type=EventType.DOOR_OPENED,
        source_layer=SourceLayer.PHYSICAL,
        timestamp=timestamp,
        building_id=building_id,
        zone_id=zone_id,
        device_id=sensor_device_id,
        user_id=None,  # door sensor cannot identify a user on its own
        severity_raw=SeverityRaw.INFO,
        payload=DoorOpenedPayload(
            door_id=door_id,
            associated_badge_event_id=associated_badge_event_id,
        ),
    )


def make_door_closed_event(
    *,
    timestamp: datetime,
    building_id: str,
    zone_id: str,
    sensor_device_id: str,
    door_id: str,
    open_duration_seconds: float,
) -> UnifiedEvent:
    """Door CLOSE event, emitted some seconds after a DOOR_OPENED."""
    return UnifiedEvent(
        event_type=EventType.DOOR_CLOSED,
        source_layer=SourceLayer.PHYSICAL,
        timestamp=timestamp,
        building_id=building_id,
        zone_id=zone_id,
        device_id=sensor_device_id,
        user_id=None,
        severity_raw=SeverityRaw.INFO,
        payload=DoorClosedPayload(
            door_id=door_id,
            open_duration_seconds=open_duration_seconds,
        ),
    )


def make_door_forced_event(
    *,
    timestamp: datetime,
    building_id: str,
    zone_id: str,
    sensor_device_id: str,
    door_id: str,
    no_badge_window_seconds: float = 10.0,
) -> UnifiedEvent:
    """
    Forced door event — opened without a preceding badge access in the
    correlation window. High-severity by construction.

    Used by attack scenarios in 2c, exposed here for completeness.
    """
    return UnifiedEvent(
        event_type=EventType.DOOR_FORCED,
        source_layer=SourceLayer.PHYSICAL,
        timestamp=timestamp,
        building_id=building_id,
        zone_id=zone_id,
        device_id=sensor_device_id,
        user_id=None,
        severity_raw=SeverityRaw.ALERT,
        payload=DoorForcedPayload(
            door_id=door_id,
            no_badge_window_seconds=no_badge_window_seconds,
        ),
    )
