"""
Event payloads — one Pydantic model per EventType.

Each UnifiedEvent carries a `payload` field whose schema depends on
`event_type`. We use a Pydantic discriminated union so that:
  - validation is automatic and strict
  - mismatched payload/event_type combinations are caught at parse time
  - downstream code (feature extractor, rules engine) gets typed access

The discriminator field is `kind`, set to a Literal matching EventType.
"""

from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import AccessResult, DeviceStatus, DeviceType, DoorState


# -----------------------------------------------------------------------------
# Physical layer payloads
# -----------------------------------------------------------------------------

class BadgeAccessPayload(BaseModel):
    """Payload for EventType.BADGE_ACCESS."""

    kind: Literal["BADGE_ACCESS"] = "BADGE_ACCESS"
    badge_id: str
    reader_device_id: str
    access_result: AccessResult
    door_id: Optional[str] = Field(
        default=None,
        description="Door controlled by this reader, if any",
    )


class DoorOpenedPayload(BaseModel):
    """Payload for EventType.DOOR_OPENED."""

    kind: Literal["DOOR_OPENED"] = "DOOR_OPENED"
    door_id: str
    state: Literal[DoorState.OPEN] = DoorState.OPEN
    # If a badge was scanned within the correlation window, the middleware
    # fills this in. Useful for tailgating / forced-door rules.
    associated_badge_event_id: Optional[UUID] = None


class DoorClosedPayload(BaseModel):
    """Payload for EventType.DOOR_CLOSED."""

    kind: Literal["DOOR_CLOSED"] = "DOOR_CLOSED"
    door_id: str
    state: Literal[DoorState.CLOSED] = DoorState.CLOSED
    open_duration_seconds: Optional[float] = Field(
        default=None,
        description="How long the door was open before closing",
    )


class DoorForcedPayload(BaseModel):
    """
    Payload for EventType.DOOR_FORCED.

    Emitted when the door sensor reports OPEN but no associated badge event
    was seen within the correlation window. This is a high-signal event.
    """

    kind: Literal["DOOR_FORCED"] = "DOOR_FORCED"
    door_id: str
    state: Literal[DoorState.FORCED] = DoorState.FORCED
    no_badge_window_seconds: float = Field(
        ...,
        description="Window during which no badge was observed",
    )


class MotionDetectedPayload(BaseModel):
    """Payload for EventType.MOTION_DETECTED."""

    kind: Literal["MOTION_DETECTED"] = "MOTION_DETECTED"
    detector_device_id: str
    # The motion sensor cannot identify users; it only counts moving entities.
    # `entity_count` > 1 paired with a single badge access is the tailgating
    # signal.
    entity_count: int = Field(default=1, ge=1)


class CameraEventPayload(BaseModel):
    """
    Payload for EventType.CAMERA_EVENT.

    Per the architecture doc (section 2): no real video, only metadata.
    """

    kind: Literal["CAMERA_EVENT"] = "CAMERA_EVENT"
    camera_device_id: str
    event_label: str = Field(
        ...,
        description="Label produced by upstream CV (e.g. 'person', 'object_left')",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


# -----------------------------------------------------------------------------
# Cyber layer payloads
# -----------------------------------------------------------------------------

class NetworkFlowPayload(BaseModel):
    """
    Payload for EventType.NETWORK_FLOW.

    Aggregated flow record over a short window (e.g. 1 minute), produced
    by the network agent.
    """

    kind: Literal["NETWORK_FLOW"] = "NETWORK_FLOW"
    src_ip: str
    dst_ip: str
    bytes_out: int = Field(..., ge=0)
    bytes_in: int = Field(..., ge=0)
    distinct_dst_ports: int = Field(
        default=1,
        ge=0,
        description="Number of distinct destination ports in this window",
    )
    window_seconds: float = Field(default=60.0, gt=0)


class NetworkAnomalyPayload(BaseModel):
    """
    Payload for EventType.NETWORK_ANOMALY.

    Pre-classified anomaly emitted by the network agent (e.g. SYN burst,
    exfiltration). The AI engine still scores it -- this is just a hint.
    """

    kind: Literal["NETWORK_ANOMALY"] = "NETWORK_ANOMALY"
    anomaly_label: str = Field(
        ...,
        description="e.g. 'PORT_SCAN', 'EXFILTRATION', 'C2_BEACON'",
    )
    src_ip: str
    severity_hint: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Source-side estimate, NOT the final AI score",
    )


# -----------------------------------------------------------------------------
# Device health payload
# -----------------------------------------------------------------------------

class DeviceStatusPayload(BaseModel):
    """Payload for EventType.DEVICE_STATUS — heartbeat or status change."""

    kind: Literal["DEVICE_STATUS"] = "DEVICE_STATUS"
    device_type: DeviceType
    status: DeviceStatus
    last_seen_seconds_ago: float = Field(default=0.0, ge=0.0)


# -----------------------------------------------------------------------------
# Discriminated union
# -----------------------------------------------------------------------------

EventPayload = Annotated[
    Union[
        BadgeAccessPayload,
        DoorOpenedPayload,
        DoorClosedPayload,
        DoorForcedPayload,
        MotionDetectedPayload,
        CameraEventPayload,
        NetworkFlowPayload,
        NetworkAnomalyPayload,
        DeviceStatusPayload,
    ],
    Field(discriminator="kind"),
]
