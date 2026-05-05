"""
Kafka producer for the middleware.

Publishes every accepted event on the `events.raw` topic, in the
UnifiedEvent JSON format defined by the AI engine schemas. The JSON
shape is identical to what `ai_engine_client.to_unified_event()`
produces for the HTTP path — this module just forwards bytes to Kafka
instead of POSTing them.

Lifecycle:
  - The producer is created lazily on first send (so the middleware
    starts even if Kafka is unreachable).
  - `flush()` is called on shutdown via FastAPI's lifespan hook.
  - Errors are logged but never propagated to the HTTP handler — losing
    a Kafka publish must not cause the middleware to reject the event.

This module is a no-op when settings.KAFKA_ENABLED is False.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class KafkaPublisher:
    """Thread-safe lazy-init Kafka producer."""

    def __init__(self) -> None:
        self._producer = None
        self._lock = threading.Lock()
        self._failed_init = False
        self._first_success_logged = False

    def _ensure(self) -> Optional[Any]:
        """Return a connected producer or None if Kafka is disabled / unreachable."""
        if not settings.KAFKA_ENABLED:
            return None
        if self._failed_init:
            return None
        if self._producer is not None:
            return self._producer

        with self._lock:
            if self._producer is not None:
                return self._producer
            try:
                from kafka import KafkaProducer  # type: ignore
                self._producer = KafkaProducer(
                    bootstrap_servers=settings.KAFKA_BROKERS,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    acks=1,
                    linger_ms=10,
                    retries=3,
                )
                logger.info("kafka producer connected: %s", settings.KAFKA_BROKERS)
            except Exception as e:  # noqa: BLE001
                logger.warning("kafka producer init failed: %s", e)
                self._failed_init = True
                return None
        return self._producer

    def _on_send_success(self, metadata) -> None:
        # First successful broker ack — log once at INFO to confirm the path is alive.
        if not self._first_success_logged:
            self._first_success_logged = True
            logger.info(
                "kafka first delivery confirmed: topic=%s partition=%s offset=%s",
                metadata.topic, metadata.partition, metadata.offset,
            )
        else:
            logger.debug(
                "kafka delivery: topic=%s partition=%s offset=%s",
                metadata.topic, metadata.partition, metadata.offset,
            )

    def _on_send_error(self, exc) -> None:
        logger.warning("kafka delivery failed: %s", exc)

    def send_unified_event(self, payload: dict) -> None:
        """Publish a UnifiedEvent dict on `events.raw`."""
        producer = self._ensure()
        if producer is None:
            return  # disabled or down — caller continues with HTTP fallback
        try:
            future = producer.send(settings.KAFKA_TOPIC_RAW, value=payload)
            future.add_callback(self._on_send_success)
            future.add_errback(self._on_send_error)
        except Exception as e:  # noqa: BLE001
            logger.warning("kafka send failed: %s", e)

    def flush(self, timeout: float = 2.0) -> None:
        if self._producer is not None:
            try:
                self._producer.flush(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass

    def close(self, timeout: float = 2.0) -> None:
        if self._producer is not None:
            try:
                self._producer.flush(timeout=timeout)
                self._producer.close(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass
            self._producer = None


# Module-level singleton.
publisher = KafkaPublisher()