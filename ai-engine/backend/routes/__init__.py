"""HTTP / WebSocket routes for the SOC backend."""

from . import alerts, devices, events, logs, score, users, ws

__all__ = ["alerts", "devices", "events", "logs", "score", "users", "ws"]