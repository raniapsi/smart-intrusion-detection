"""
WebSocket connection manager.

A trivial pub/sub: every connected client receives every broadcast.
For a SOC dashboard with 1-3 simultaneous viewers this is more than
adequate; we don't need rooms or per-client filters.

Lifecycle:
  - `connect(ws)` is awaited inside the route handler before yielding.
  - `disconnect(ws)` is called when the client drops.
  - `broadcast(message)` is called by the replay thread.

Thread safety: the manager is touched from both the asyncio event loop
(connect/disconnect/broadcast) and from a background replay thread that
schedules broadcasts onto the loop. We use `asyncio.run_coroutine_threadsafe`
in `replay.py` to bridge the two.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Tracks connected clients and broadcasts JSON-serialisable messages."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        logger.info("client connected; total=%d", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self._clients.remove(ws)
        except ValueError:
            pass
        logger.info("client disconnected; total=%d", len(self._clients))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Send a JSON-serialisable message to every connected client.
        Drops clients whose send fails (assumed dead).
        """
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def n_clients(self) -> int:
        return len(self._clients)