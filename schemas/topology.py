"""
Building topology — static reference data.

This is the model loaded from `config.yaml` (see section 2.1 of architecture doc).
It describes WHAT exists in the simulated building: zones, users, devices, doors.

The AI engine uses this for:
  - feature enrichment (zone sensitivity, expected user zones)
  - rule-based detection (e.g. "user in zone outside their typical set")
  - dashboard display (building map)

This is loaded ONCE at startup and held in memory. It does not change
during a run (a new run = a new YAML if the topology changes).
"""

from datetime import time
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import DeviceType, ZoneSensitivity


class Zone(BaseModel):
    """A logical area of the building (e.g. 'Z3 — Server Room')."""

    zone_id: str = Field(..., description="Unique zone identifier, e.g. 'Z3'")
    building_id: str = Field(..., description="Parent building, e.g. 'B1'")
    name: str = Field(..., description="Human-readable name")
    sensitivity: ZoneSensitivity = Field(
        default=ZoneSensitivity.STANDARD,
        description="Sensitivity tier — affects anomaly scoring weights",
    )
    # Optional 2D coordinates for the SOC dashboard map.
    # Coordinates are in arbitrary floor-plan units; the frontend rescales them.
    map_x: Optional[float] = None
    map_y: Optional[float] = None


class UserProfile(BaseModel):
    """
    A registered user (employee).

    With the 'employees only' decision, all users share the same role.
    The 'typical_*' fields describe the GROUND TRUTH baseline used by
    the dataset generator. The AI engine itself does NOT read these
    fields directly — it learns the baseline from the training data.
    They are kept here for:
      - reproducible dataset generation
      - sanity-checking AI predictions during validation
    """

    user_id: str = Field(..., description="Unique user identifier")
    name: str = Field(..., description="Display name")
    badge_id: str = Field(..., description="Associated badge identifier")

    # Ground-truth baseline (used by dataset generator only)
    typical_zones: list[str] = Field(
        default_factory=list,
        description="Zones this user typically frequents",
    )
    typical_arrival: time = Field(
        ...,
        description="Mean arrival time (gaussian centre)",
    )
    typical_departure: time = Field(
        ...,
        description="Mean departure time (gaussian centre)",
    )
    arrival_std_minutes: float = Field(
        default=45.0,
        description="Std dev of arrival distribution, in minutes",
    )
    departure_std_minutes: float = Field(
        default=30.0,
        description="Std dev of departure distribution, in minutes",
    )


class Device(BaseModel):
    """An IoT device installed in a zone."""

    device_id: str = Field(..., description="Unique device identifier")
    type: DeviceType
    zone_id: str = Field(..., description="Zone where the device is installed")
    # The IP address is only meaningful for devices that emit network traffic
    # (cameras typically do, badge readers usually don't).
    ip_address: Optional[str] = None


class Door(BaseModel):
    """A door, optionally instrumented with a sensor and/or a badge reader."""

    door_id: str = Field(..., description="Unique door identifier")
    zone_id: str = Field(..., description="Zone the door gives access to")
    sensor_device_id: Optional[str] = Field(
        default=None,
        description="Door sensor device, if instrumented",
    )
    reader_device_id: Optional[str] = Field(
        default=None,
        description="Badge reader device, if controlled",
    )


class BuildingTopology(BaseModel):
    """Root document loaded from config.yaml."""

    building_id: str
    zones: list[Zone]
    users: list[UserProfile]
    devices: list[Device]
    doors: list[Door]

    @field_validator("zones")
    @classmethod
    def _zones_unique(cls, v: list[Zone]) -> list[Zone]:
        ids = [z.zone_id for z in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate zone_id in topology")
        return v

    @field_validator("users")
    @classmethod
    def _users_unique(cls, v: list[UserProfile]) -> list[UserProfile]:
        ids = [u.user_id for u in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate user_id in topology")
        badges = [u.badge_id for u in v]
        if len(badges) != len(set(badges)):
            raise ValueError("Duplicate badge_id in topology")
        return v

    def zone_index(self) -> dict[str, Zone]:
        """Quick lookup by zone_id."""
        return {z.zone_id: z for z in self.zones}

    def user_index(self) -> dict[str, UserProfile]:
        """Quick lookup by user_id."""
        return {u.user_id: u for u in self.users}

    def device_index(self) -> dict[str, Device]:
        """Quick lookup by device_id."""
        return {d.device_id: d for d in self.devices}
