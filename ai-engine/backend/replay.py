"""
Temporal replay.

Walks through the loaded events in chronological order and broadcasts
them on the WebSocket at a controlled cadence. This is the "live demo"
mechanism: the dashboard sees events arrive as if Node-RED were producing
them in real time, except 60 seconds of simulated time elapse per second
of wall clock by default.

Implementation: a daemon thread that sleeps between events. The thread
schedules `WebSocketManager.broadcast()` onto the asyncio event loop via
`run_coroutine_threadsafe`, which is the safe way to mix blocking
threads with asyncio.

Why not asyncio task? Because uvicorn's event loop is busy serving HTTP
requests; doing time.sleep() on it would freeze the API. A separate
thread with its own pace is cleaner.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from schemas import AIClassification, EnrichedEvent

from .datastore import Datastore
from .ws_manager import WebSocketManager

logger = logging.getLogger(__name__)


# 1 second of wall clock = SPEED_FACTOR seconds of simulated time.
DEFAULT_SPEED_FACTOR: float = 60.0

# Maximum sleep between broadcasts. Even if the next event is 1h of
# simulated time away, we don't want to make the user wait. We cap and
# move on (the next event will still play in order).
MAX_SLEEP_SECONDS: float = 5.0

# Only broadcast non-NORMAL events to avoid drowning the dashboard in
# heartbeat traffic. Configurable.
DEFAULT_BROADCAST_NORMAL: bool = False


class ReplayController:
    """
    Manages a background replay thread.

    Use:
        controller = ReplayController(store, ws_manager, loop)
        controller.start()                # begins the replay
        controller.stop()                 # stops it (on app shutdown)
    """

    def __init__(
        self,
        *,
        store: Datastore,
        ws_manager: WebSocketManager,
        loop: asyncio.AbstractEventLoop,
        speed_factor: float = DEFAULT_SPEED_FACTOR,
        broadcast_normal: bool = DEFAULT_BROADCAST_NORMAL,
    ) -> None:
        self._store = store
        self._ws = ws_manager
        self._loop = loop
        self._speed = speed_factor
        self._broadcast_normal = broadcast_normal
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="replay", daemon=True,
        )
        self._thread.start()
        logger.info(
            "replay started (speed_factor=%.1f, broadcast_normal=%s)",
            self._speed, self._broadcast_normal,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("replay stopped")

    # ---- main loop ----------------------------------------------------------

    def _run(self) -> None:
        events = self._store.all_events()
        if not events:
            logger.warning("replay: no events to replay")
            return

        prev_ts: Optional[datetime] = None
        for ev in events:
            if self._stop_event.is_set():
                break

            # Sleep proportionally to the gap to the previous event.
            if prev_ts is not None:
                gap_seconds = (ev.timestamp - prev_ts).total_seconds()
                wall_sleep = min(MAX_SLEEP_SECONDS, gap_seconds / self._speed)
                if wall_sleep > 0:
                    # Use Event.wait so stop() is responsive.
                    if self._stop_event.wait(timeout=wall_sleep):
                        break
            prev_ts = ev.timestamp

            if not self._broadcast_normal and ev.ai_classification == AIClassification.NORMAL:
                continue

            # Bridge to the asyncio loop for the actual send.
            self._broadcast(ev)

    def _broadcast(self, ev: EnrichedEvent) -> None:
        """Schedule a broadcast on the asyncio loop from this thread."""
        message = {
            "type": "event",
            "event_id": str(ev.event_id),
            "timestamp": ev.timestamp.isoformat(),
            "event_type": ev.event_type.value,
            "zone_id": ev.zone_id,
            "device_id": ev.device_id,
            "user_id": ev.user_id,
            "ai_score": ev.ai_score,
            "ai_classification": ev.ai_classification.value,
        }
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ws.broadcast(message), self._loop,
            )
            # Don't wait for the result — fire and forget.
            future.add_done_callback(self._log_send_error)
        except RuntimeError:
            # The loop might be closing during shutdown.
            pass

    @staticmethod
    def _log_send_error(future) -> None:
        try:
            future.result()
        except Exception as e:  # noqa: BLE001
            logger.debug("ws broadcast failed: %s", e)