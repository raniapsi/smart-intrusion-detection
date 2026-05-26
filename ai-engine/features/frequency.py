"""
Frequency features — sliding-window counters of recent events.

Stateful: maintains deques of timestamps per (user_id, zone_id, event-type)
key and prunes them as time advances.

Memory characteristic: O(W * E) where W = max window size and E = active
keys. For 50 users + 8 zones + 1h windows, this stays small.

Streaming-friendly: the same code is used in batch (extracting features
from a JSONL) and in streaming (extracting features from a Kafka stream
in step 6). The only requirement is that events arrive in non-decreasing
timestamp order, which the orchestrator guarantees.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from schemas import AccessResult, BadgeAccessPayload, EventType, UnifiedEvent


# Window sizes used by the features below.
WINDOW_5MIN = timedelta(minutes=5)
WINDOW_1H = timedelta(hours=1)
WINDOW_24H = timedelta(hours=24)


class FrequencyState:
    """
    Stateful tracker for sliding-window event counts.

    The state holds, per key, a deque of timestamps. On each event we:
      1. Append the new timestamp to the deque(s) for the relevant key(s).
      2. Pop from the front any timestamps older than the largest window.

    `count_within(key, window)` returns the number of timestamps within
    the window, computed by linear scan from the back -- O(events_in_window).
    For our scale this is plenty fast.
    """

    def __init__(self) -> None:
        # Per-user event timestamps, regardless of event type.
        self._user_events: dict[str, deque[datetime]] = defaultdict(deque)
        # Per-zone event timestamps.
        self._zone_events: dict[str, deque[datetime]] = defaultdict(deque)
        # DENIED-badge timestamps, indexed by user.
        self._user_denied: dict[str, deque[datetime]] = defaultdict(deque)
        # DENIED-badge timestamps, indexed by zone.
        self._zone_denied: dict[str, deque[datetime]] = defaultdict(deque)

    # ---- update -------------------------------------------------------------

    def observe(self, event: UnifiedEvent) -> None:
        """
        Update the state with a new event. Must be called in non-decreasing
        timestamp order.

        Pruning: anything older than 24h (the largest window) is removed
        from each deque. This keeps memory bounded.
        """
        t = event.timestamp

        if event.user_id is not None:
            self._user_events[event.user_id].append(t)
            self._prune(self._user_events[event.user_id], t - WINDOW_24H)

        self._zone_events[event.zone_id].append(t)
        self._prune(self._zone_events[event.zone_id], t - WINDOW_24H)

        # Track DENIED badge attempts specifically.
        if event.event_type == EventType.BADGE_ACCESS:
            payload = event.payload
            if isinstance(payload, BadgeAccessPayload) and \
                    payload.access_result == AccessResult.DENIED:
                # Even if user_id is None (unknown badge), bucket by badge_id
                # under a synthetic user key so repeated denied attempts are
                # tracked. We use "badge:<id>" as the synthetic key.
                key = event.user_id if event.user_id is not None \
                    else f"badge:{payload.badge_id}"
                self._user_denied[key].append(t)
                self._prune(self._user_denied[key], t - WINDOW_24H)

                self._zone_denied[event.zone_id].append(t)
                self._prune(self._zone_denied[event.zone_id], t - WINDOW_24H)

    @staticmethod
    def _prune(dq: deque[datetime], threshold: datetime) -> None:
        """Pop from the left while the leftmost timestamp is older than threshold."""
        while dq and dq[0] < threshold:
            dq.popleft()

    # ---- query --------------------------------------------------------------

    @staticmethod
    def _count_within(dq: deque[datetime], window_start: datetime) -> int:
        """Count timestamps >= window_start, walking from the back."""
        n = 0
        # Walk in reverse; deques support indexed access in O(1) per index
        # for short tails, but iteration from the right is what we want.
        for ts in reversed(dq):
            if ts >= window_start:
                n += 1
            else:
                break
        return n

    def events_for_user(
        self, user_id: Optional[str], at: datetime, window: timedelta
    ) -> int:
        """Number of events recorded for `user_id` in [at - window, at]."""
        if user_id is None:
            return 0
        dq = self._user_events.get(user_id)
        if dq is None:
            return 0
        return self._count_within(dq, at - window)

    def events_for_zone(
        self, zone_id: str, at: datetime, window: timedelta
    ) -> int:
        dq = self._zone_events.get(zone_id)
        if dq is None:
            return 0
        return self._count_within(dq, at - window)

    def denied_for_user(
        self,
        user_id: Optional[str],
        badge_id: Optional[str],
        at: datetime,
        window: timedelta,
    ) -> int:
        """
        Counts DENIED badge attempts. Falls back to badge_id when user_id
        is None (unknown badge attempts still need to be counted).
        """
        if user_id is not None:
            dq = self._user_denied.get(user_id)
        elif badge_id is not None:
            dq = self._user_denied.get(f"badge:{badge_id}")
        else:
            dq = None
        if dq is None:
            return 0
        return self._count_within(dq, at - window)

    def denied_for_zone(
        self, zone_id: str, at: datetime, window: timedelta
    ) -> int:
        dq = self._zone_denied.get(zone_id)
        if dq is None:
            return 0
        return self._count_within(dq, at - window)