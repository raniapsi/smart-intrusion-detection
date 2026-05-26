"""
Unified Event Schema — the canonical event format flowing through Kafka.

Two related models:

  - UnifiedEvent: produced by Node-RED (middleware), consumed by AI engine.
                  ai_score and ai_classification are None.

  - EnrichedEvent: produced by AI engine, consumed by dashboard / DB.
                   ai_score and ai_classification are filled.

Both share the same wire format; the only difference is whether the AI
fields are populated. This lets us serialise/deserialise interchangeably
and keep one schema in TimescaleDB.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import AIClassification, EventType, SeverityRaw, SourceLayer
from .payloads import EventPayload


# Schema version follows semver. Bump MAJOR for breaking changes,
# MINOR for additive changes (new optional fields).
SCHEMA_VERSION = "1.0.0"


class UnifiedEvent(BaseModel):
    """
    Normalised event as it flows on Kafka topic `events.raw`.

    Produced by Node-RED after MQTT ingestion + normalisation + enrichment
    (see section 5.2 of the architecture doc).
    """

    model_config = ConfigDict(
        # Reject unknown fields -- catches typos and outdated producers.
        extra="forbid",
        # Validate on assignment as well as on construction.
        validate_assignment=True,
    )

    # -------- Identity --------
    event_id: UUID = Field(default_factory=uuid4)
    schema_version: str = Field(default=SCHEMA_VERSION)

    # -------- Type & layer --------
    event_type: EventType
    source_layer: SourceLayer

    # -------- Timing --------
    # `timestamp` is when the event happened in the field.
    # `ingestion_timestamp` is when Node-RED received it, used to measure
    # pipeline latency and to handle out-of-order events.
    timestamp: datetime
    ingestion_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # -------- Location --------
    building_id: str
    zone_id: str
    device_id: str

    # -------- Subject --------
    # `user_id` is None for unattributed events (network flow, motion alone,
    # forced door without badge).
    user_id: Optional[str] = None

    # -------- Severity & payload --------
    severity_raw: SeverityRaw = Field(default=SeverityRaw.INFO)
    payload: EventPayload

    # -------- Correlation hints from middleware --------
    # Filled by Node-RED's correlation flow (section 5.2, Flow 3).
    correlated_events: list[UUID] = Field(default_factory=list)

    # -------- AI fields (None on UnifiedEvent, filled on EnrichedEvent) --------
    ai_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ai_classification: Optional[AIClassification] = None

    # -------- Validators --------

    @field_validator("timestamp", "ingestion_timestamp")
    @classmethod
    def _require_timezone_aware(cls, v: datetime) -> datetime:
        """
        All timestamps MUST be timezone-aware (preferably UTC).

        A naive datetime would silently break the 10-second correlation
        windows used by the rules engine, since comparisons across DST
        boundaries or producer timezones would be wrong.
        """
        if v.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware "
                "(use datetime.now(timezone.utc) or similar)"
            )
        return v

    @field_validator("ingestion_timestamp")
    @classmethod
    def _ingestion_after_event(cls, v: datetime, info) -> datetime:
        """
        Sanity check: ingestion can be ~equal to or after the event timestamp,
        but not significantly before. We allow a small negative drift (1s)
        because clocks between simulated devices and the host can be slightly
        out of sync.
        """
        ts = info.data.get("timestamp")
        if ts is not None:
            drift = (v - ts).total_seconds()
            if drift < -1.0:
                raise ValueError(
                    f"ingestion_timestamp is {-drift:.2f}s before timestamp; "
                    "check clock sync"
                )
        return v

    @model_validator(mode="after")
    def _payload_matches_event_type(self) -> "UnifiedEvent":
        """
        Cross-field validation: event_type and payload.kind MUST agree.

        The discriminated union on `payload` validates the payload's internal
        structure against its own `kind`, but does NOT check that this `kind`
        matches the top-level `event_type`. Without this validator, a producer
        could send event_type=BADGE_ACCESS with a NetworkAnomalyPayload and
        the event would be silently accepted.

        This is the kind of bug `extra="forbid"` exists to prevent; we extend
        that strictness here to inter-field consistency.
        """
        # `payload.kind` is set by the discriminated union (Literal field).
        # `event_type` is an EventType enum; .value gives the wire string.
        if self.event_type.value != self.payload.kind:
            raise ValueError(
                f"event_type '{self.event_type.value}' does not match "
                f"payload.kind '{self.payload.kind}'"
            )
        return self


class EnrichedEvent(UnifiedEvent):
    """
    A UnifiedEvent after the AI engine has scored and classified it.

    The AI fields are non-optional here (enforced via validator).
    Published on Kafka topic `events.enriched`.
    """

    ai_score: float = Field(..., ge=0.0, le=1.0)
    ai_classification: AIClassification

    @field_validator("ai_classification")
    @classmethod
    def _classification_matches_score(
        cls, v: AIClassification, info
    ) -> AIClassification:
        """
        Enforce the score-to-class mapping defined in section 7.3:
            [0.0, 0.3) -> NORMAL
            [0.3, 0.7) -> SUSPECT
            [0.7, 1.0] -> CRITICAL

        This catches bugs where the scorer and classifier disagree.
        """
        score = info.data.get("ai_score")
        if score is None:
            return v
        if score < 0.3:
            expected = AIClassification.NORMAL
        elif score < 0.7:
            expected = AIClassification.SUSPECT
        else:
            expected = AIClassification.CRITICAL
        if v != expected:
            raise ValueError(
                f"ai_classification {v} inconsistent with score {score:.3f}; "
                f"expected {expected}"
            )
        return v
