"""
In-memory datastore for the SOC backend.

Loads enriched events + alerts JSONL files at startup, indexes them, and
serves filtered queries to the API routes. No database required.

Threading model:
  - Reads are concurrent (FastAPI runs them on a thread pool by default).
  - Mutations (acknowledge an alert) take a lock — they're rare so this
    is fine.
  - The replay thread mutates `_replay_index` only; readers never block
    on it.

Memory footprint: ~360k events × ~1KB per EnrichedEvent object ≈ 360 MB
worst case if you load the full 30-day baseline. For the demo we
recommend loading only one or two scenarios at a time.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from uuid import UUID

from schemas import (
    AIClassification,
    Alert,
    BuildingTopology,
    EnrichedEvent,
    UserProfile,
)


class Datastore:
    """
    In-memory store for enriched events, alerts, and topology.

    Loading model:
      - One topology YAML
      - 1..N enriched JSONL files (concatenated)
      - 1..N alerts JSONL files (concatenated)
    """

    def __init__(self, topology: BuildingTopology) -> None:
        self._topo = topology
        self._events: list[EnrichedEvent] = []
        self._alerts: list[Alert] = []

        # Indices for fast queries
        self._events_by_zone: dict[str, list[EnrichedEvent]] = defaultdict(list)
        self._events_by_user: dict[str, list[EnrichedEvent]] = defaultdict(list)
        self._events_by_class: dict[AIClassification, list[EnrichedEvent]] = defaultdict(list)
        self._alerts_by_id: dict[UUID, Alert] = {}

        self._lock = threading.Lock()

    # ---- loading -----------------------------------------------------------

    def load_events_jsonl(self, path: Path) -> int:
        """Load enriched events from a JSONL file. Returns count loaded."""
        n = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = EnrichedEvent.model_validate_json(line)
                self._index_event(ev)
                n += 1
        return n

    def load_alerts_jsonl(self, path: Path) -> int:
        """Load alerts from a JSONL file. Returns count loaded."""
        n = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                al = Alert.model_validate_json(line)
                self._index_alert(al)
                n += 1
        return n

    def _index_event(self, ev: EnrichedEvent) -> None:
        self._events.append(ev)
        self._events_by_zone[ev.zone_id].append(ev)
        if ev.user_id is not None:
            self._events_by_user[ev.user_id].append(ev)
        self._events_by_class[ev.ai_classification].append(ev)

    def _index_alert(self, al: Alert) -> None:
        self._alerts.append(al)
        self._alerts_by_id[al.alert_id] = al

    def finalise(self) -> None:
        """Sort all indices by timestamp once loading is complete."""
        self._events.sort(key=lambda e: e.timestamp)
        for lst in self._events_by_zone.values():
            lst.sort(key=lambda e: e.timestamp)
        for lst in self._events_by_user.values():
            lst.sort(key=lambda e: e.timestamp)
        for lst in self._events_by_class.values():
            lst.sort(key=lambda e: e.timestamp)
        self._alerts.sort(key=lambda a: a.created_at)

    # ---- queries -----------------------------------------------------------

    def topology(self) -> BuildingTopology:
        return self._topo

    def all_events(self) -> list[EnrichedEvent]:
        return self._events

    def query_events(
        self,
        *,
        zone: Optional[str] = None,
        user_id: Optional[str] = None,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
        classification: Optional[AIClassification] = None,
        limit: Optional[int] = None,
    ) -> list[EnrichedEvent]:
        """
        Filter events by zone / user / time / classification.
        Multiple filters combine with AND.
        """
        # Pick the smallest pre-indexed pool to start from.
        if zone is not None:
            pool: Iterable[EnrichedEvent] = self._events_by_zone.get(zone, [])
        elif user_id is not None:
            pool = self._events_by_user.get(user_id, [])
        elif classification is not None:
            pool = self._events_by_class.get(classification, [])
        else:
            pool = self._events

        results: list[EnrichedEvent] = []
        for ev in pool:
            if zone is not None and ev.zone_id != zone:
                continue
            if user_id is not None and ev.user_id != user_id:
                continue
            if classification is not None and ev.ai_classification != classification:
                continue
            if from_ts is not None and ev.timestamp < from_ts:
                continue
            if to_ts is not None and ev.timestamp > to_ts:
                continue
            results.append(ev)
            if limit is not None and len(results) >= limit:
                break
        return results

    def all_alerts(self) -> list[Alert]:
        return self._alerts

    def active_alerts(self) -> list[Alert]:
        """Non-acknowledged alerts."""
        return [a for a in self._alerts if not a.acknowledged]

    def get_alert(self, alert_id: UUID) -> Optional[Alert]:
        return self._alerts_by_id.get(alert_id)

    def acknowledge_alert(
        self, alert_id: UUID, by: str, at: datetime
    ) -> Optional[Alert]:
        """
        Mark an alert as acknowledged. Returns the updated alert, or None
        if the id is unknown.
        """
        with self._lock:
            alert = self._alerts_by_id.get(alert_id)
            if alert is None:
                return None
            alert.acknowledged = True
            alert.acknowledged_by = by
            alert.acknowledged_at = at
            return alert

    # ---- topology helpers ---------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserProfile]:
        return self._topo.user_index().get(user_id)

    def all_users(self) -> list[UserProfile]:
        return list(self._topo.users)

    def all_devices(self):
        return list(self._topo.devices)

    # ---- aggregate score ----------------------------------------------------

    def current_zone_scores(self) -> dict[str, float]:
        """
        For each zone, return the MAX ai_score of the most recent N events
        (a "current threat level" gauge for the dashboard map).
        """
        N = 50
        out: dict[str, float] = {}
        for z in self._topo.zones:
            recent = self._events_by_zone.get(z.zone_id, [])[-N:]
            if not recent:
                out[z.zone_id] = 0.0
            else:
                out[z.zone_id] = max(e.ai_score for e in recent)
        return out