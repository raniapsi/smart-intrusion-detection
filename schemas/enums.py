"""
Enumerated types used across the Unified Event Schema.

These enums are the canonical vocabulary shared between:
  - the simulator (producer of raw events)
  - Node-RED middleware (normalises into UnifiedEvent)
  - the AI engine (consumes UnifiedEvent, produces EnrichedEvent / Alert)
  - the dashboard (displays EnrichedEvent / Alert)

Any new value MUST be added here first, then propagated to all consumers.
"""

from enum import Enum


class EventType(str, Enum):
    """
    The kind of event being reported.

    Each value corresponds to a specific payload schema (see payloads.py).
    Using str-based Enum so JSON serialisation gives the readable name.
    """

    # Physical layer events
    BADGE_ACCESS = "BADGE_ACCESS"
    DOOR_OPENED = "DOOR_OPENED"
    DOOR_CLOSED = "DOOR_CLOSED"
    DOOR_FORCED = "DOOR_FORCED"
    MOTION_DETECTED = "MOTION_DETECTED"
    CAMERA_EVENT = "CAMERA_EVENT"

    # Cyber layer events
    NETWORK_FLOW = "NETWORK_FLOW"
    NETWORK_ANOMALY = "NETWORK_ANOMALY"

    # Device health events (heartbeat / silent device)
    DEVICE_STATUS = "DEVICE_STATUS"


class SourceLayer(str, Enum):
    """Whether the event comes from physical sensors or cyber telemetry."""

    PHYSICAL = "PHYSICAL"
    CYBER = "CYBER"


class AccessResult(str, Enum):
    """Outcome of a badge read at a reader."""

    GRANTED = "GRANTED"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"


class DoorState(str, Enum):
    """Current physical state of a door."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FORCED = "FORCED"  # opened without an associated badge event


class DeviceType(str, Enum):
    """Category of IoT device."""

    BADGE_READER = "BADGE_READER"
    DOOR_SENSOR = "DOOR_SENSOR"
    MOTION_DETECTOR = "MOTION_DETECTOR"
    CAMERA = "CAMERA"


class DeviceStatus(str, Enum):
    """Operational state of an IoT device."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"  # responsive but missing heartbeats / late


class SeverityRaw(str, Enum):
    """
    Raw severity assigned by the source (sensor or middleware rule),
    BEFORE the AI engine has scored the event.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"


class AIClassification(str, Enum):
    """
    Output of the AI engine's risk classification.

    Mapping from score (see section 7.3 of the architecture doc):
        score in [0.0, 0.3)  -> NORMAL
        score in [0.3, 0.7)  -> SUSPECT
        score in [0.7, 1.0]  -> CRITICAL
    """

    NORMAL = "NORMAL"
    SUSPECT = "SUSPECT"
    CRITICAL = "CRITICAL"


class ZoneSensitivity(str, Enum):
    """
    Sensitivity tier of a zone. Used for feature engineering: anomalous
    accesses to high-sensitivity zones are weighted more heavily.

    Note: with the 'employees only, no roles' choice, this is NOT a
    permission boundary -- all users CAN access all zones. It only
    reflects how unusual access is in the baseline, and how costly an
    anomaly there would be.
    """

    PUBLIC = "PUBLIC"          # lobby, cafeteria
    STANDARD = "STANDARD"      # offices, meeting rooms
    RESTRICTED = "RESTRICTED"  # archives, comms rooms
    CRITICAL = "CRITICAL"      # data center, server room


class NetworkAnomalyLabel(str, Enum):
    """
    Canonical labels for pre-classified network anomalies.

    Emitted by the network agent (cyber side) as a hint to the AI engine.
    The AI still computes its own score; this is just a starting signal,
    not a verdict. The set is closed (Pydantic enforces) so the rules
    engine and feature extractor can pattern-match safely.
    """

    PORT_SCAN = "PORT_SCAN"          # SYN burst across many ports
    EXFILTRATION = "EXFILTRATION"    # outbound volume far above baseline
    C2_BEACON = "C2_BEACON"          # periodic small outbound to a fixed dst
    LATERAL_MOVEMENT = "LATERAL_MOVEMENT"  # internal scan (one src, many dsts)
    DOS = "DOS"                      # denial of service signal
    UNKNOWN = "UNKNOWN"              # generic anomaly without further info