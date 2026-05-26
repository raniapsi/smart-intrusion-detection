"""WebSocket route — pushes events from the replay loop to the dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    """
    Push real-time events from the temporal replay to the connected client.

    On connect, the server sends a small `hello` message with current
    statistics (number of pending alerts, zone count). Then the replay
    thread broadcasts events as their simulated time arrives.
    """
    manager = ws.app.state.ws_manager
    store = ws.app.state.store

    await manager.connect(ws)
    try:
        # Initial hello so the client knows the connection is live.
        await ws.send_json({
            "type": "hello",
            "n_active_alerts": len(store.active_alerts()),
            "n_zones": len(store.topology().zones),
            "n_events": len(store.all_events()),
        })

        # The replay thread does the rest. We just need to keep the
        # connection alive until the client closes it.
        while True:
            # `receive_text` blocks until the client sends something OR
            # the connection drops, at which point WebSocketDisconnect
            # is raised. We don't process inbound messages (the dashboard
            # is read-only over WS), but we have to read for the loop
            # to make progress.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:  # noqa: BLE001
        logger.exception("ws error: %s", e)
        manager.disconnect(ws)