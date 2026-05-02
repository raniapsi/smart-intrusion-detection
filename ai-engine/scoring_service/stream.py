"""
Streaming driver — SKELETON.

This file defines the interface the streaming code WILL use when the
Kafka infrastructure is available (steps 6 & 9 of the project plan).
For now the actual Kafka calls are stubbed out and clearly marked as
TODOs. The shape of the code is settled so step 9 will be a fill-in.

Design notes:
  - The pipeline already supports `process_event()` for one-at-a-time
    processing. We just need a producer/consumer harness around it.
  - For correlation: in true streaming we cannot look ahead. The
    correlator can run on a small ring buffer of recent events
    (see TODO below). Cyber typically lags physical, so a 60s lookback
    catches most useful correlations.
  - Two output topics per the README:
      events.enriched (every processed event)
      alerts.critical (only non-NORMAL events)

Required environment to run for real (NOT in this file's tests):
  - a Kafka broker (localhost:9092 by default)
  - a Mosquitto/Node-RED upstream feeding events.raw
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from schemas import Alert, EnrichedEvent

from .pipeline import ScoringPipeline


@dataclass
class StreamConfig:
    """
    Configuration for the streaming driver. All fields have defaults so
    the runner can be instantiated even when Kafka isn't present yet —
    construction won't fail; only `run()` will.
    """

    kafka_brokers: str = "localhost:9092"
    consumer_topic: str = "events.raw"
    producer_topic_enriched: str = "events.enriched"
    producer_topic_alerts: str = "alerts.critical"
    consumer_group: str = "ai-engine-scoring"
    # Buffer size for the correlation lookback window. With 60s window and
    # ~50 events/s peak the buffer fits in low-MB memory.
    correlation_buffer_size: int = 4096


class StreamRunner:
    """
    Skeleton runner. Construction is cheap (no Kafka contact). `run()` is
    where Kafka I/O would live; right now it raises NotImplementedError.

    To implement step 9 (or earlier if needed), replace the bodies of the
    `_consume`, `_produce_enriched`, and `_produce_alert` methods.
    """

    def __init__(
        self, *, pipeline: ScoringPipeline, config: StreamConfig
    ) -> None:
        self._pipeline = pipeline
        self._config = config

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    def run(self) -> None:
        """
        Main loop: consume → process → produce.

        This is intentionally not implemented yet. Calling `run()` raises
        NotImplementedError with a pointer to step 9. Tests exercise the
        construction and the helpers (`process_one`) but never call run().
        """
        raise NotImplementedError(
            "Streaming runtime is a step-9 deliverable. "
            "Use scoring_service.batch.run_batch_jsonl() until then. "
            "When implementing, replace _consume/_produce_* with your "
            "Kafka client of choice (e.g. confluent-kafka-python)."
        )

    # -------------------------------------------------------------------------
    # Helpers — exercised by tests
    # -------------------------------------------------------------------------

    def process_one(self, event_json: str) -> tuple[EnrichedEvent, Optional[Alert]]:
        """
        Single event in, (enriched, optional alert) out.

        Designed to be wrapped by the (not-yet-implemented) Kafka loop:
            for raw in self._consume():
                enriched, alert = self.process_one(raw)
                self._produce_enriched(enriched)
                if alert is not None:
                    self._produce_alert(alert)
        """
        from schemas import UnifiedEvent
        event = UnifiedEvent.model_validate_json(event_json)
        return self._pipeline.process_event(event)

    # -------------------------------------------------------------------------
    # Kafka stubs — to be implemented in step 9
    # -------------------------------------------------------------------------

    def _consume(self):  # pragma: no cover  (no Kafka in tests)
        """
        TODO step 9: yield raw event JSON strings from the Kafka consumer.
        """
        raise NotImplementedError("kafka consumer not wired yet")

    def _produce_enriched(self, enriched: EnrichedEvent) -> None:  # pragma: no cover
        """
        TODO step 9: send the enriched event to events.enriched.
        """
        raise NotImplementedError("kafka producer not wired yet")

    def _produce_alert(self, alert: Alert) -> None:  # pragma: no cover
        """
        TODO step 9: send the alert to alerts.critical.
        """
        raise NotImplementedError("kafka producer not wired yet")