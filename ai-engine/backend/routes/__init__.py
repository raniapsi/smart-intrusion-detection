"""HTTP / WebSocket routes for the SOC backend."""

from . import alerts, devices, events, ingest, logs, score, users, ws

__all__ = [
    "alerts", "devices", "events", "ingest", "logs", "score", "users", "ws",
]
