"""
FastAPI application factory.

`create_app()` is the single entry point used by:
  - the CLI (uvicorn launcher in cli.py)
  - the test suite

It returns a fully wired app with:
  - the in-memory Datastore loaded from configurable paths
  - the WebSocketManager
  - the ReplayController (started on startup, stopped on shutdown)
  - the optional Kafka StreamRunner (started on startup if --kafka-brokers
    is provided)
  - all routers mounted (events, alerts, users, devices, score, ingest,
    logs, ws)
  - permissive CORS

Two ingestion paths coexist:
  - Kafka consumer (canonical, declared in the README): events arrive on
    events.raw; the consumer scores them, produces to events.enriched +
    alerts.critical, and updates the in-memory store + WebSocket.
  - HTTP /api/ingest/events (fallback, useful for curl tests / demos
    without a Kafka cluster): same processing path, no Kafka publishing.

Both paths feed into the SAME ScoringPipeline.process_event() and the
SAME datastore, so query results stay consistent across consumers.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dataset.topology import load_topology
from scoring_service import ScoringPipeline
from scoring_service.stream import (
    StreamConfig,
    StreamRunner,
    make_ws_broadcast_hook,
)

from .datastore import Datastore
from .replay import DEFAULT_SPEED_FACTOR, ReplayController
from .routes import alerts, devices, events, ingest, logs, score, users, ws
from .ws_manager import WebSocketManager

logger = logging.getLogger(__name__)


@dataclass
class BackendConfig:
    """All configuration needed to bring the backend up."""

    topology_path: Path
    enriched_paths: list[Path] = field(default_factory=list)
    alerts_paths: list[Path] = field(default_factory=list)
    replay_speed_factor: float = DEFAULT_SPEED_FACTOR
    enable_replay: bool = True
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    baselines_path: Optional[Path] = None
    model_path: Optional[Path] = None

    # Kafka — optional. When kafka_brokers is provided AND the pipeline
    # can be loaded (baselines + model), a Kafka consumer thread is
    # started alongside the HTTP server.
    kafka_brokers: Optional[str] = None
    kafka_topic_raw: str = "events.raw"
    kafka_topic_enriched: str = "events.enriched"
    kafka_topic_alerts: str = "alerts.critical"
    kafka_consumer_group: str = "ai-engine-scoring"


def _build_store(config: BackendConfig) -> Datastore:
    topo = load_topology(config.topology_path)
    store = Datastore(topo)

    total_events = 0
    for path in config.enriched_paths:
        n = store.load_events_jsonl(Path(path))
        logger.info("loaded %d events from %s", n, path)
        total_events += n

    total_alerts = 0
    for path in config.alerts_paths:
        n = store.load_alerts_jsonl(Path(path))
        logger.info("loaded %d alerts from %s", n, path)
        total_alerts += n

    store.finalise()
    logger.info(
        "datastore ready: %d events, %d alerts, %d zones, %d users",
        total_events, total_alerts,
        len(topo.zones), len(topo.users),
    )
    return store


def create_app(config: BackendConfig) -> FastAPI:
    """Build a FastAPI app wired to the given config."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- startup ----
        store = _build_store(config)
        ws_manager = WebSocketManager()
        loop = asyncio.get_running_loop()

        replay = ReplayController(
            store=store, ws_manager=ws_manager, loop=loop,
            speed_factor=config.replay_speed_factor,
        )

        pipeline: Optional[ScoringPipeline] = None
        if config.baselines_path is not None and config.model_path is not None:
            pipeline = ScoringPipeline.from_paths(
                topology_path=config.topology_path,
                baselines_path=config.baselines_path,
                model_path=config.model_path,
            )

        # Optional Kafka consumer — runs in a daemon thread.
        kafka_runner: Optional[StreamRunner] = None
        if config.kafka_brokers and pipeline is not None:
            stream_config = StreamConfig(
                kafka_brokers=config.kafka_brokers,
                consumer_topic=config.kafka_topic_raw,
                producer_topic_enriched=config.kafka_topic_enriched,
                producer_topic_alerts=config.kafka_topic_alerts,
                consumer_group=config.kafka_consumer_group,
            )
            kafka_runner = StreamRunner(
                pipeline=pipeline,
                config=stream_config,
                # Hook events into the live datastore so the dashboard
                # queries see them immediately.
                on_enriched=lambda ev: store.add_event(ev),
                on_alert=lambda al: store.add_alert(al),
            )
            # Wrap the WS broadcast in a separate hook chained after the
            # datastore one. We add it via an outer lambda since
            # StreamRunner only accepts one on_enriched.
            ws_hook = make_ws_broadcast_hook(ws_manager, loop)
            datastore_hook = kafka_runner._on_enriched  # captured above
            kafka_runner._on_enriched = _chain_hooks([datastore_hook, ws_hook])
            kafka_runner.start_in_thread()
            logger.info(
                "kafka consumer started: brokers=%s topic=%s",
                config.kafka_brokers, config.kafka_topic_raw,
            )
        elif config.kafka_brokers and pipeline is None:
            logger.warning(
                "kafka_brokers set but pipeline not configured "
                "(missing --baselines / --model); kafka consumer NOT started",
            )

        app.state.store = store
        app.state.ws_manager = ws_manager
        app.state.replay = replay
        app.state.pipeline = pipeline
        app.state.kafka_runner = kafka_runner

        if config.enable_replay:
            replay.start()

        try:
            yield
        finally:
            # ---- shutdown ----
            replay.stop()
            if kafka_runner is not None:
                kafka_runner.stop()

    app = FastAPI(
        title="SOC backend — converged IoT/AI security",
        version="0.9.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(events.router)
    app.include_router(alerts.router)
    app.include_router(users.router)
    app.include_router(devices.router)
    app.include_router(score.router)
    app.include_router(ingest.router)
    app.include_router(logs.router)
    app.include_router(ws.router)

    @app.get("/")
    def root():
        return {
            "service": "soc-backend",
            "version": "0.9.0",
            "endpoints": [
                "/api/events", "/api/alerts/active", "/api/alerts",
                "/api/alert/{id}/acknowledge",
                "/api/users", "/api/users/{user_id}/profile",
                "/api/devices", "/api/score/current", "/api/logs",
                "/api/ingest/events",
                "/ws/events",
            ],
        }

    return app


def _chain_hooks(hooks):
    """Compose multiple single-arg hooks into one. Errors in one don't stop the others."""
    def _composed(arg):
        for h in hooks:
            if h is None:
                continue
            try:
                h(arg)
            except Exception:  # noqa: BLE001
                logger.exception("hook failed")
    return _composed