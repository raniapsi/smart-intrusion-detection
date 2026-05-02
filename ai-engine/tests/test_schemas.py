"""
Validation tests for the schemas package.

These tests exercise the contracts a producer (Node-RED) and consumer
(AI engine) MUST satisfy. They double as executable documentation.
"""

from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas import (
    SCHEMA_VERSION,
    AccessResult,
    AIClassification,
    Alert,
    BadgeAccessPayload,
    BuildingTopology,
    Device,
    DeviceType,
    Door,
    DoorForcedPayload,
    EnrichedEvent,
    EventType,
    NetworkAnomalyPayload,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
    UserProfile,
    Zone,
    ZoneSensitivity,
)


# =============================================================================
# UnifiedEvent — happy path
# =============================================================================

class TestUnifiedEventHappyPath:

    def test_minimal_badge_access(self):
        """A standard badge event from Node-RED parses cleanly."""
        ev = UnifiedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 5, 1, 9, 2, 14, tzinfo=timezone.utc),
            building_id="B1",
            zone_id="Z3",
            device_id="R07",
            user_id="alice@corp",
            payload=BadgeAccessPayload(
                badge_id="1042",
                reader_device_id="R07",
                access_result=AccessResult.GRANTED,
                door_id="D-Z3-A",
            ),
        )
        assert ev.ai_score is None
        assert ev.ai_classification is None
        assert ev.schema_version == SCHEMA_VERSION
        assert ev.severity_raw == SeverityRaw.INFO

    def test_round_trip_json(self):
        """Serialise -> deserialise -> equal."""
        original = UnifiedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 5, 1, 9, 2, 14, tzinfo=timezone.utc),
            building_id="B1",
            zone_id="Z3",
            device_id="R07",
            user_id="alice@corp",
            payload=BadgeAccessPayload(
                badge_id="1042",
                reader_device_id="R07",
                access_result=AccessResult.GRANTED,
            ),
        )
        as_json = original.model_dump_json()
        restored = UnifiedEvent.model_validate_json(as_json)
        assert restored == original

    def test_unattributed_event_allows_null_user(self):
        """A forced door has no user_id -- this must be allowed."""
        ev = UnifiedEvent(
            event_type=EventType.DOOR_FORCED,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 5, 1, 3, 17, 42, tzinfo=timezone.utc),
            building_id="B1",
            zone_id="Z2",
            device_id="DS-B2",
            user_id=None,
            severity_raw=SeverityRaw.ALERT,
            payload=DoorForcedPayload(
                door_id="D-B2",
                no_badge_window_seconds=10.0,
            ),
        )
        assert ev.user_id is None


# =============================================================================
# UnifiedEvent — validation errors
# =============================================================================

class TestUnifiedEventValidation:

    def test_naive_datetime_rejected(self):
        """A naive (tz-unaware) timestamp must be rejected."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            UnifiedEvent(
                event_type=EventType.BADGE_ACCESS,
                source_layer=SourceLayer.PHYSICAL,
                timestamp=datetime(2026, 5, 1, 9, 0, 0),  # NAIVE
                building_id="B1",
                zone_id="Z3",
                device_id="R07",
                payload=BadgeAccessPayload(
                    badge_id="1042",
                    reader_device_id="R07",
                    access_result=AccessResult.GRANTED,
                ),
            )

    def test_payload_kind_must_match_event_type(self):
        """Wrong payload type for the event_type is caught by the union."""
        with pytest.raises(ValidationError):
            # Network anomaly payload but event_type says BADGE_ACCESS
            UnifiedEvent(
                event_type=EventType.BADGE_ACCESS,
                source_layer=SourceLayer.PHYSICAL,
                timestamp=datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
                building_id="B1",
                zone_id="Z3",
                device_id="R07",
                payload=NetworkAnomalyPayload(
                    anomaly_label="PORT_SCAN",
                    src_ip="10.0.0.5",
                    severity_hint=0.8,
                ),
            )

    def test_unknown_field_rejected(self):
        """Extra fields are rejected -- catches typos in producers."""
        with pytest.raises(ValidationError):
            UnifiedEvent.model_validate({
                "event_type": "BADGE_ACCESS",
                "source_layer": "PHYSICAL",
                "timestamp": "2026-05-01T09:00:00+00:00",
                "building_id": "B1",
                "zone_id": "Z3",
                "device_id": "R07",
                "payload": {
                    "kind": "BADGE_ACCESS",
                    "badge_id": "1042",
                    "reader_device_id": "R07",
                    "access_result": "GRANTED",
                },
                "typo_field": "oops",  # should fail
            })

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            UnifiedEvent(
                event_type=EventType.BADGE_ACCESS,
                source_layer=SourceLayer.PHYSICAL,
                timestamp=datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
                building_id="B1",
                zone_id="Z3",
                device_id="R07",
                payload=BadgeAccessPayload(
                    badge_id="1042",
                    reader_device_id="R07",
                    access_result=AccessResult.GRANTED,
                ),
                ai_score=1.5,  # > 1.0
            )

    def test_ingestion_before_event_rejected(self):
        """Ingestion timestamp significantly before event timestamp fails."""
        ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        bad_ingestion = ts - timedelta(seconds=30)
        with pytest.raises(ValidationError, match="before timestamp"):
            UnifiedEvent(
                event_type=EventType.BADGE_ACCESS,
                source_layer=SourceLayer.PHYSICAL,
                timestamp=ts,
                ingestion_timestamp=bad_ingestion,
                building_id="B1",
                zone_id="Z3",
                device_id="R07",
                payload=BadgeAccessPayload(
                    badge_id="1042",
                    reader_device_id="R07",
                    access_result=AccessResult.GRANTED,
                ),
            )


# =============================================================================
# EnrichedEvent — score / classification consistency
# =============================================================================

class TestEnrichedEventConsistency:

    def _base_kwargs(self):
        return dict(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
            building_id="B1",
            zone_id="Z3",
            device_id="R07",
            payload=BadgeAccessPayload(
                badge_id="1042",
                reader_device_id="R07",
                access_result=AccessResult.GRANTED,
            ),
        )

    @pytest.mark.parametrize("score,expected", [
        (0.0, AIClassification.NORMAL),
        (0.15, AIClassification.NORMAL),
        (0.299, AIClassification.NORMAL),
        (0.3, AIClassification.SUSPECT),
        (0.5, AIClassification.SUSPECT),
        (0.699, AIClassification.SUSPECT),
        (0.7, AIClassification.CRITICAL),
        (0.95, AIClassification.CRITICAL),
        (1.0, AIClassification.CRITICAL),
    ])
    def test_score_class_mapping(self, score, expected):
        ev = EnrichedEvent(
            **self._base_kwargs(),
            ai_score=score,
            ai_classification=expected,
        )
        assert ev.ai_classification == expected

    def test_inconsistent_class_rejected(self):
        """Score 0.1 with CRITICAL must fail."""
        with pytest.raises(ValidationError, match="inconsistent"):
            EnrichedEvent(
                **self._base_kwargs(),
                ai_score=0.1,
                ai_classification=AIClassification.CRITICAL,
            )


# =============================================================================
# Alert
# =============================================================================

class TestAlert:

    def test_critical_alert_ok(self):
        alert = Alert(
            triggering_event_id=uuid4(),
            building_id="B1",
            zone_id="Z2",
            user_id=None,
            classification=AIClassification.CRITICAL,
            score=0.95,
            title="Forced door in zone Z2",
            description="Door D-B2 forced at 03:17:42 UTC, no badge in window.",
            contributing_detectors=["rule:door_forced"],
            suggested_action="lock_door:D-B2",
        )
        assert not alert.acknowledged
        assert alert.acknowledged_at is None

    def test_normal_classification_rejected(self):
        with pytest.raises(ValidationError, match="NORMAL"):
            Alert(
                triggering_event_id=uuid4(),
                building_id="B1",
                zone_id="Z2",
                classification=AIClassification.NORMAL,
                score=0.05,
                title="x",
                description="x",
            )


# =============================================================================
# Topology
# =============================================================================

class TestTopology:

    def test_minimal_topology(self):
        topo = BuildingTopology(
            building_id="B1",
            zones=[
                Zone(zone_id="Z1", building_id="B1", name="Lobby",
                     sensitivity=ZoneSensitivity.PUBLIC),
                Zone(zone_id="Z3", building_id="B1", name="Server Room",
                     sensitivity=ZoneSensitivity.CRITICAL),
            ],
            users=[
                UserProfile(
                    user_id="u001", name="Alice", badge_id="b001",
                    typical_zones=["Z1", "Z3"],
                    typical_arrival=time(9, 0),
                    typical_departure=time(18, 0),
                ),
            ],
            devices=[
                Device(device_id="R07", type=DeviceType.BADGE_READER,
                       zone_id="Z3"),
            ],
            doors=[
                Door(door_id="D-Z3-A", zone_id="Z3",
                     reader_device_id="R07"),
            ],
        )
        assert len(topo.zones) == 2
        assert topo.zone_index()["Z3"].sensitivity == ZoneSensitivity.CRITICAL
        assert topo.user_index()["u001"].name == "Alice"

    def test_duplicate_zone_id_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate zone_id"):
            BuildingTopology(
                building_id="B1",
                zones=[
                    Zone(zone_id="Z1", building_id="B1", name="A"),
                    Zone(zone_id="Z1", building_id="B1", name="B"),
                ],
                users=[],
                devices=[],
                doors=[],
            )

    def test_duplicate_badge_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate badge_id"):
            BuildingTopology(
                building_id="B1",
                zones=[Zone(zone_id="Z1", building_id="B1", name="A")],
                users=[
                    UserProfile(
                        user_id="u1", name="A", badge_id="bX",
                        typical_arrival=time(9, 0),
                        typical_departure=time(18, 0),
                    ),
                    UserProfile(
                        user_id="u2", name="B", badge_id="bX",  # duplicate
                        typical_arrival=time(9, 0),
                        typical_departure=time(18, 0),
                    ),
                ],
                devices=[],
                doors=[],
            )