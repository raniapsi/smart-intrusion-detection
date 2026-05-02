"""
Tests for step 6 — the end-to-end scoring service.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dataset.generators import Rng, generate_day
from dataset.scenarios import REGISTRY
from dataset.topology import load_topology
from features import BaselineCatalog, FeatureExtractor, learn_baselines
from models import train_isolation_forest
from schemas import (
    AIClassification,
    Alert,
    EnrichedEvent,
    EventType,
    UnifiedEvent,
)
from scoring_service import (
    PipelineComponents,
    ScoringPipeline,
    StreamConfig,
    StreamRunner,
    build_alert_from_enriched,
)
from scoring_service.batch import run_batch_jsonl


TOPO_PATH = (
    Path(__file__).resolve().parents[2] / "dataset" / "topology" / "building_b1.yaml"
)


@pytest.fixture(scope="module")
def topo():
    return load_topology(TOPO_PATH)


@pytest.fixture(scope="module")
def trained_pipeline(topo):
    """A ScoringPipeline with a freshly-trained IF on one day of normal data."""
    rng = Rng(seed=42)
    train_events = generate_day(topo=topo, day=date(2026, 4, 1), rng=rng)
    catalog = learn_baselines(train_events)
    extractor = FeatureExtractor(topology=topo, baselines=catalog)
    train_df = extractor.extract_dataframe(train_events)
    model = train_isolation_forest(train_df, n_estimators=50)

    components = PipelineComponents(
        topology=topo, baselines=catalog, model=model,
    )
    return ScoringPipeline(components)


# =============================================================================
# Pipeline behaviour
# =============================================================================

class TestPipelineBatch:

    def test_returns_one_enriched_per_input(self, topo, trained_pipeline):
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)
        enriched, alerts = trained_pipeline.run_batch(events)
        assert len(enriched) == len(events)
        # Order is preserved.
        for e_in, e_out in zip(events, enriched):
            assert e_in.event_id == e_out.event_id

    def test_enriched_events_have_ai_fields(self, topo, trained_pipeline):
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)
        enriched, _ = trained_pipeline.run_batch(events[:200])
        for ev in enriched:
            assert isinstance(ev, EnrichedEvent)
            assert 0.0 <= ev.ai_score <= 1.0
            assert ev.ai_classification in {
                AIClassification.NORMAL,
                AIClassification.SUSPECT,
                AIClassification.CRITICAL,
            }

    def test_alerts_only_for_non_normal(self, topo, trained_pipeline):
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)
        enriched, alerts = trained_pipeline.run_batch(events)
        # Every alert references an event that is NOT classified NORMAL.
        non_normal_ids = {
            e.event_id for e in enriched
            if e.ai_classification != AIClassification.NORMAL
        }
        for a in alerts:
            assert a.triggering_event_id in non_normal_ids
        # And no NORMAL event has an alert.
        alert_ids = {a.triggering_event_id for a in alerts}
        for e in enriched:
            if e.ai_classification == AIClassification.NORMAL:
                assert e.event_id not in alert_ids

    def test_forced_door_attack_is_critical(self, topo, trained_pipeline):
        """End-to-end: feed a scenario, expect CRITICAL alert on DOOR_FORCED."""
        scenario = REGISTRY["forced_door"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "forced_door"),
        )
        enriched, alerts = trained_pipeline.run_batch(result.events)

        # Find the DOOR_FORCED enriched event.
        forced_evs = [
            e for e in enriched
            if e.event_type == EventType.DOOR_FORCED
        ]
        assert len(forced_evs) >= 1
        for fe in forced_evs:
            assert fe.ai_classification == AIClassification.CRITICAL

        # And there's an alert for that event.
        forced_ids = {e.event_id for e in forced_evs}
        forced_alerts = [a for a in alerts if a.triggering_event_id in forced_ids]
        assert len(forced_alerts) >= 1
        # Alert title mentions the door
        assert "Door" in forced_alerts[0].title

    def test_empty_input(self, trained_pipeline):
        enriched, alerts = trained_pipeline.run_batch([])
        assert enriched == []
        assert alerts == []


# =============================================================================
# Pipeline streaming-API
# =============================================================================

class TestPipelineProcessEvent:

    def test_single_event(self, topo, trained_pipeline):
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)
        ev = events[0]
        enriched, alert = trained_pipeline.process_event(ev)
        assert isinstance(enriched, EnrichedEvent)
        assert enriched.event_id == ev.event_id
        # alert may or may not be present; if present it's an Alert.
        if alert is not None:
            assert isinstance(alert, Alert)


# =============================================================================
# Batch JSONL driver
# =============================================================================

class TestBatchJsonlDriver:

    def test_jsonl_round_trip(self, topo, trained_pipeline, tmp_path):
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)
        # Write events to a JSONL.
        events_path = tmp_path / "events.jsonl"
        with events_path.open("w") as f:
            for ev in events:
                f.write(ev.model_dump_json())
                f.write("\n")

        enriched_out = tmp_path / "enriched.jsonl"
        alerts_out = tmp_path / "alerts.jsonl"
        n_enr, n_alr = run_batch_jsonl(
            pipeline=trained_pipeline,
            events_path=events_path,
            enriched_out=enriched_out,
            alerts_out=alerts_out,
        )
        assert n_enr == len(events)
        # Re-parse the enriched JSONL — should validate as EnrichedEvent.
        with enriched_out.open() as f:
            lines = f.readlines()
        assert len(lines) == n_enr
        for line in lines[:5]:
            EnrichedEvent.model_validate_json(line)

        # Alerts file: each line is an Alert.
        with alerts_out.open() as f:
            alert_lines = f.readlines()
        assert len(alert_lines) == n_alr
        for line in alert_lines[:5]:
            Alert.model_validate_json(line)


# =============================================================================
# Stream skeleton
# =============================================================================

class TestStreamSkeleton:

    def test_construction_does_not_touch_kafka(self, trained_pipeline):
        """Construction must succeed without any Kafka broker present."""
        runner = StreamRunner(
            pipeline=trained_pipeline,
            config=StreamConfig(),
        )
        assert runner is not None

    def test_run_raises_not_implemented(self, trained_pipeline):
        runner = StreamRunner(
            pipeline=trained_pipeline,
            config=StreamConfig(),
        )
        with pytest.raises(NotImplementedError):
            runner.run()

    def test_process_one_works_via_json(self, topo, trained_pipeline):
        """The streaming entry point must be able to round-trip JSON."""
        rng = Rng(seed=42)
        ev = generate_day(topo=topo, day=date(2026, 4, 8), rng=rng)[0]
        runner = StreamRunner(
            pipeline=trained_pipeline,
            config=StreamConfig(),
        )
        enriched, _ = runner.process_one(ev.model_dump_json())
        assert isinstance(enriched, EnrichedEvent)
        assert enriched.event_id == ev.event_id


# =============================================================================
# Alert builder
# =============================================================================

class TestAlertBuilder:

    def test_normal_classification_rejected(self, topo, trained_pipeline):
        """build_alert_from_enriched must refuse NORMAL events.
        (Enforced by the Alert schema, not the builder, but we double-check.)"""
        # Build a fake EnrichedEvent that's NORMAL — schema will reject the
        # alert at construction time.
        from schemas import (
            BadgeAccessPayload, AccessResult, EventType, SeverityRaw,
            SourceLayer,
        )
        from datetime import datetime, timezone
        ev = EnrichedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
            building_id="B1", zone_id="Z1", device_id="R-Z1",
            user_id="u001",
            severity_raw=SeverityRaw.INFO,
            payload=BadgeAccessPayload(
                badge_id="b001", reader_device_id="R-Z1",
                access_result=AccessResult.GRANTED,
            ),
            ai_score=0.05,
            ai_classification=AIClassification.NORMAL,
        )
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            build_alert_from_enriched(
                enriched=ev, rule_hits=None,
                score_if=0.05, score_rules=0.0, correlation_peer=0.0,
            )