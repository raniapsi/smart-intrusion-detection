from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class EventType(str, Enum):
    BADGE_ACCESS = "badge_access"
    DOOR_SENSOR = "door_sensor"
    MOTION_DETECTED = "motion_detected"
    NETWORK_ANOMALY = "network_anomaly"
    IOT_TRAFFIC = "iot_traffic"


class Event(BaseModel):
    event_id: str = Field(..., description="Unique event identifier")
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_device: str = Field(..., description="Device or sensor ID")
    location: str = Field(..., description="Zone or room identifier")
    details: dict = Field(default_factory=dict, description="Additional event data")
