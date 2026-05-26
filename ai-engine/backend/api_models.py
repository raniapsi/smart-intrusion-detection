"""
API response models.

These are the SHAPE of what the REST endpoints return. Kept separate
from the internal `schemas` package so we can:
  - tweak the wire format without breaking internal code
  - omit/rename fields for the dashboard's convenience
  - add computed fields (e.g. n_events_total in a user profile)

All models use Pydantic v2 with str-mode UUIDs (the dashboard expects
plain strings, not UUID objects).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EventOut(BaseModel):
    """Event as exposed by GET /api/events."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    timestamp: datetime
    event_type: str
    source_layer: str
    zone_id: str
    device_id: str
    user_id: Optional[str]
    ai_score: float
    ai_classification: str


class AlertOut(BaseModel):
    """Alert as exposed by GET /api/alerts/active."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    created_at: datetime
    triggering_event_id: str
    building_id: str
    zone_id: str
    user_id: Optional[str]
    classification: str
    score: float
    title: str
    description: str
    contributing_detectors: list[str]
    suggested_action: Optional[str]
    acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]


class UserProfileOut(BaseModel):
    """User profile + access stats."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    name: str
    badge_id: str
    typical_zones: list[str]
    typical_arrival: str
    typical_departure: str
    n_events_total: int
    n_critical_events: int
    n_suspect_events: int
    last_seen: Optional[datetime]


class DeviceOut(BaseModel):
    """Device entry for GET /api/devices."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    type: str
    zone_id: str
    ip_address: Optional[str]


class ZoneScoreOut(BaseModel):
    """Per-zone current threat level."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str
    zone_name: str
    sensitivity: str
    current_score: float
    classification: str


class CurrentScoreOut(BaseModel):
    """GET /api/score/current — overall building threat snapshot."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    building_id: str
    zones: list[ZoneScoreOut]
    n_active_alerts: int


class AcknowledgeIn(BaseModel):
    """POST /api/alert/{alert_id}/acknowledge body."""

    model_config = ConfigDict(extra="forbid")

    by: str = Field(..., min_length=1, max_length=100)


class AcknowledgeOut(BaseModel):
    """Response to ack."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    acknowledged: bool
    acknowledged_by: str
    acknowledged_at: datetime


class LogOut(BaseModel):
    """
    GET /api/logs entry.

    For now this is just a wrapper around EventOut with an extra
    `signature` field that is None (the PQC log signing is the security
    team's scope — see README section 4.3). Kept as a separate model so
    the dashboard's "Logs" tab has its own type.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    timestamp: datetime
    event_type: str
    zone_id: str
    user_id: Optional[str]
    ai_score: float
    ai_classification: str
    # Placeholder for the PQC signature delivered by the security team.
    # Always None for now.
    signature: Optional[str] = None