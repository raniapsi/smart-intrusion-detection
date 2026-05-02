"""
FastAPI application factory.

`create_app()` is the single entry point used by:
  - the CLI (uvicorn launcher in cli.py)
  - the test suite

It returns a fully wired app with:
  - the in-memory Datastore loaded from configurable paths
  - the WebSocketManager
  - the ReplayController (started on startup, stopped on shutdown)
  - all routers mounted
  - permissive CORS (we serve a separate React dev server at :5173)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dataset.topology import load_topology

from .datastore import Datastore
from .replay import DEFAULT_SPEED_FACTOR, ReplayController
from .routes import alerts, devices, events, logs, score, users, ws
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
        app.state.store = store
        app.state.ws_manager = ws_manager
        app.state.replay = replay

        if config.enable_replay:
            replay.start()

        try:
            yield
        finally:
            # ---- shutdown ----
            replay.stop()

    app = FastAPI(
        title="SOC backend — converged IoT/AI security",
        version="0.7.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(events.router)
    app.include_router(alerts.router)
    app.include_router(users.router)
    app.include_router(devices.router)
    app.include_router(score.router)
    app.include_router(logs.router)
    app.include_router(ws.router)

    @app.get("/")
    def root():
        return {
            "service": "soc-backend",
            "version": "0.7.0",
            "endpoints": [
                "/api/events", "/api/alerts/active", "/api/alerts",
                "/api/alert/{id}/acknowledge",
                "/api/users", "/api/users/{user_id}/profile",
                "/api/devices", "/api/score/current", "/api/logs",
                "/ws/events",
            ],
        }

    return app