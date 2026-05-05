"""
Streaming driver — Kafka consumer + producer.

Replaces the step-6 skeleton with a working implementation that:
  - consumes events from `events.raw`
  - runs each event through the ScoringPipeline (the same pipeline used
    by the batch driver and the HTTP /api/ingest endpoint)
  - produces the enriched event to `events.enriched`
  - produces alerts to `alerts.critical` (only non-NORMAL classifications)
  - optionally calls hooks (e.g. to also push into the in-memory datastore
    and the WebSocket broadcaster, when running inside the FastAPI process)

Threading model:
  - The consumer loop is BLOCKING (kafka-python doesn't offer asyncio).
  - When run from the FastAPI app, we put the consumer in a daemon thread
    so it doesn't block the HTTP server. Hooks are invoked synchronously
    from that thread — the datastore is thread-safe (lock), and the
    WebSocket broadcast is bridged to the asyncio loop via
    run_coroutine_threadsafe (same pattern as ReplayController).
  - When run as a standalone CLI (no FastAPI), we just block on the loop.

Configuration:
  - All connection params come via the StreamConfig dataclass; the CLI
    reads them from environment variables / command-line flags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from schemas import Alert, EnrichedEvent, UnifiedEvent

from .pipeline import ScoringPipeline

logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    """Connection + topology parameters for the Kafka stream."""

    kafka_brokers: str = "localhost:9092"
    consumer_topic: str = "events.raw"
    producer_topic_enriched: str = "events.enriched"
    producer_topic_alerts: str = "alerts.critical"
    consumer_group: str = "ai-engine-scoring"
    # Time the consumer waits between polls when idle. Lower = more
    # responsive, higher = lower CPU.
    poll_timeout_ms: int = 1000


class StreamRunner:
    """
    Kafka consumer + producer wrapping a ScoringPipeline.

    Two ways to use it:

    1) Standalone CLI (blocking):
         runner.start()        # spins up the loop in the calling thread
         # blocks until SIGINT / runner.stop() is called

    2) From the FastAPI app (background thread):
         thread = runner.start_in_thread(
             on_enriched=..., on_alert=...,
         )
         # the thread runs the loop; the main process serves HTTP
    """

    def __init__(
        self,
        *,
        pipeline: ScoringPipeline,
        config: StreamConfig,
        on_enriched: Optional[Callable[[EnrichedEvent], None]] = None,
        on_alert: Optional[Callable[[Alert], None]] = None,
    ) -> None:
        self._pipeline = pipeline
        self._config = config
        # User-supplied hooks called for every processed event/alert,
        # in addition to publishing on Kafka. The FastAPI app uses these
        # to keep its in-memory datastore and WebSocket broadcaster in
        # sync — without coupling this module to either.
        self._on_enriched = on_enriched
        self._on_alert = on_alert

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Kafka clients are imported lazily so this module can be loaded
        # in environments where kafka-python isn't installed (e.g. unit
        # tests of process_event() that don't touch the network).
        self._consumer = None
        self._producer = None

    # -------------------------------------------------------------------------
    # Public entry points
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Run the consumer loop in the calling thread (blocks)."""
        self._stop_event.clear()
        self._connect()
        try:
            self._loop()
        finally:
            self._disconnect()

    def start_in_thread(self) -> threading.Thread:
        """Start the consumer loop in a daemon thread; returns the thread."""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_safely,
            name="kafka-stream",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the loop to exit and wait for the thread (if any)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._disconnect()

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _run_safely(self) -> None:
        """Thread entry point: connect, loop, log on any error."""
        try:
            self._connect()
            self._loop()
        except Exception as e:  # noqa: BLE001
            logger.exception("kafka stream crashed: %s", e)
        finally:
            self._disconnect()

    def _connect(self) -> None:
        """Create the Kafka consumer + producer. Lazy-imports kafka-python."""
        from kafka import KafkaConsumer, KafkaProducer  # type: ignore

        cfg = self._config
        logger.info(
            "kafka stream connecting brokers=%s topic=%s group=%s",
            cfg.kafka_brokers, cfg.consumer_topic, cfg.consumer_group,
        )

        self._consumer = KafkaConsumer(
            cfg.consumer_topic,
            bootstrap_servers=cfg.kafka_brokers,
            group_id=cfg.consumer_group,
            value_deserializer=lambda v: v.decode("utf-8") if v else None,
            # auto offset reset = "earliest" so a fresh demo replays the
            # whole topic; switch to "latest" for production-style runs.
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            consumer_timeout_ms=cfg.poll_timeout_ms,
        )

        self._producer = KafkaProducer(
            bootstrap_servers=cfg.kafka_brokers,
            value_serializer=lambda v: v.encode("utf-8"),
            # We accept low-latency over strict durability for a POC.
            acks=1,
            linger_ms=10,
        )

    def _disconnect(self) -> None:
        if self._consumer is not None:
            try:
                self._consumer.close()
            except Exception:  # noqa: BLE001
                pass
            self._consumer = None
        if self._producer is not None:
            try:
                self._producer.flush(timeout=2.0)
                self._producer.close(timeout=2.0)
            except Exception:  # noqa: BLE001
                pass
            self._producer = None

    def _loop(self) -> None:
        """Main consumer loop. Polls Kafka, processes events, produces results."""
        if self._consumer is None:
            raise RuntimeError("consumer not connected")

        n_processed = 0
        while not self._stop_event.is_set():
            # `consumer_timeout_ms` makes the iterator return after that
            # many ms of no messages; we re-enter the while to check the
            # stop flag.
            try:
                for message in self._consumer:
                    if self._stop_event.is_set():
                        break
                    if message.value is None:
                        continue
                    try:
                        self._process_one(message.value)
                        n_processed += 1
                        if n_processed % 100 == 0:
                            logger.info("kafka stream processed %d events", n_processed)
                    except Exception as e:  # noqa: BLE001
                        # We never want a bad message to kill the loop.
                        logger.exception("failed to process event: %s", e)
            except StopIteration:
                # consumer_timeout_ms reached, no messages; loop and
                # re-check stop flag.
                continue

        logger.info("kafka stream stopped after %d events", n_processed)

    def _process_one(self, raw_json: str) -> None:
        """One event through the pipeline + hooks + producers."""
        event = UnifiedEvent.model_validate_json(raw_json)
        enriched, alert = self._pipeline.process_event(event)

        # 1) Local hooks (datastore / websocket) FIRST so the dashboard
        # sees the event as fast as possible, even before Kafka publishing.
        if self._on_enriched is not None:
            try:
                self._on_enriched(enriched)
            except Exception as e:  # noqa: BLE001
                logger.exception("on_enriched hook failed: %s", e)
        if alert is not None and self._on_alert is not None:
            try:
                self._on_alert(alert)
            except Exception as e:  # noqa: BLE001
                logger.exception("on_alert hook failed: %s", e)

        # 2) Publish to Kafka (events.enriched, alerts.critical)
        if self._producer is not None:
            self._producer.send(
                self._config.producer_topic_enriched,
                value=enriched.model_dump_json(),
            )
            if alert is not None:
                self._producer.send(
                    self._config.producer_topic_alerts,
                    value=alert.model_dump_json(),
                )

    # -------------------------------------------------------------------------
    # Helper exposed for HTTP /api/ingest fallback
    # -------------------------------------------------------------------------

    def process_one(self, event_json: str) -> tuple[EnrichedEvent, Optional[Alert]]:
        """
        Single event in, (enriched, optional alert) out.

        Used by the HTTP fallback endpoint when Kafka is not the source.
        Does NOT publish to Kafka — the HTTP path is for debugging/fallback
        and should not pollute the canonical event stream.
        """
        event = UnifiedEvent.model_validate_json(event_json)
        return self._pipeline.process_event(event)


# -----------------------------------------------------------------------------
# Helper used by the FastAPI app to wire WS broadcast from a thread
# -----------------------------------------------------------------------------

def make_ws_broadcast_hook(
    ws_manager,
    loop: asyncio.AbstractEventLoop,
) -> Callable[[EnrichedEvent], None]:
    """
    Build a hook that broadcasts an enriched event over the WebSocket.

    The hook is called from the Kafka consumer thread; we bridge to the
    asyncio loop with run_coroutine_threadsafe — same pattern as
    ReplayController.
    """
    def _hook(enriched: EnrichedEvent) -> None:
        if enriched.ai_classification.value == "NORMAL":
            return  # don't drown the dashboard with heartbeats
        message = {
            "type": "event",
            "event_id": str(enriched.event_id),
            "timestamp": enriched.timestamp.isoformat(),
            "event_type": enriched.event_type.value,
            "zone_id": enriched.zone_id,
            "device_id": enriched.device_id,
            "user_id": enriched.user_id,
            "ai_score": enriched.ai_score,
            "ai_classification": enriched.ai_classification.value,
        }
        try:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(message), loop,
            )
        except RuntimeError:
            pass
    return _hook