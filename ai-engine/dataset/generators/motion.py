"""
Motion detection event generator.

A motion sensor is dumb: it counts moving entities in its zone over a
short polling window. It cannot identify them. We emit one event per
detection (i.e. a poll where entity_count >= 1).

Tailgating signal: entity_count > 1 paired with a single badge event in
the same zone within a few seconds. Generated only by attack scenarios.
"""

from __future__ import annotations

from datetime import datetime

from schemas import (
    EventType,
    MotionDetectedPayload,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
)


def make_motion_event(
    *,
    timestamp: datetime,
    building_id: str,
    zone_id: str,
    detector_device_id: str,
    entity_count: int = 1,
) -> UnifiedEvent:
    """Single MOTION_DETECTED event."""
    if entity_count < 1:
        raise ValueError("entity_count must be >= 1")
    return UnifiedEvent(
        event_type=EventType.MOTION_DETECTED,
        source_layer=SourceLayer.PHYSICAL,
        timestamp=timestamp,
        building_id=building_id,
        zone_id=zone_id,
        device_id=detector_device_id,
        user_id=None,  # motion sensor never knows which user
        severity_raw=SeverityRaw.INFO,
        payload=MotionDetectedPayload(
            detector_device_id=detector_device_id,
            entity_count=entity_count,
        ),
    )
