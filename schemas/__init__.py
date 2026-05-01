"""
ai-engine schemas package.

Public API: import what you need directly from this package, e.g.:

    from schemas import UnifiedEvent, EnrichedEvent, Alert
    from schemas import EventType, AIClassification
"""

from .alerts import Alert
from .enums import (
    AccessResult,
    AIClassification,
    DeviceStatus,
    DeviceType,
    DoorState,
    EventType,
    SeverityRaw,
    SourceLayer,
    ZoneSensitivity,
)
from .events import SCHEMA_VERSION, EnrichedEvent, UnifiedEvent
from .payloads import (
    BadgeAccessPayload,
    CameraEventPayload,
    DeviceStatusPayload,
    DoorClosedPayload,
    DoorForcedPayload,
    DoorOpenedPayload,
    EventPayload,
    MotionDetectedPayload,
    NetworkAnomalyPayload,
    NetworkFlowPayload,
)
from .topology import BuildingTopology, Device, Door, UserProfile, Zone

__all__ = [
    # Versioning
    "SCHEMA_VERSION",
    # Events
    "UnifiedEvent",
    "EnrichedEvent",
    "Alert",
    # Payloads
    "EventPayload",
    "BadgeAccessPayload",
    "DoorOpenedPayload",
    "DoorClosedPayload",
    "DoorForcedPayload",
    "MotionDetectedPayload",
    "CameraEventPayload",
    "NetworkFlowPayload",
    "NetworkAnomalyPayload",
    "DeviceStatusPayload",
    # Topology
    "BuildingTopology",
    "Zone",
    "UserProfile",
    "Device",
    "Door",
    # Enums
    "EventType",
    "SourceLayer",
    "AccessResult",
    "DoorState",
    "DeviceType",
    "DeviceStatus",
    "SeverityRaw",
    "AIClassification",
    "ZoneSensitivity",
]
