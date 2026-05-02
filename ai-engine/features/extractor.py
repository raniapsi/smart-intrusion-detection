"""
Feature extractor.

Streaming-friendly: events are processed one at a time, with a stateful
window tracker. Same code is used in batch (this module's `extract_dataframe`)
and will be used in streaming (step 6, Kafka consumer).

Contract:
  - events arrive in non-decreasing timestamp order
  - the BaselineCatalog has been pre-learned on a normal dataset
  - the BuildingTopology is the static reference data

For each event, we emit one feature row. The schema is defined in
features.schema.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

import pandas as pd

from schemas import (
    BadgeAccessPayload,
    BuildingTopology,
    EventType,
    MotionDetectedPayload,
    UnifiedEvent,
)

from .baselines import BaselineCatalog
from .frequency import (
    WINDOW_1H,
    WINDOW_5MIN,
    WINDOW_24H,
    FrequencyState,
)
from .network import network_features
from .schema import COLUMN_NAMES, coerce_dataframe
from .spatial import is_typical_zone_for_user, zone_sensitivity_lvl
from .temporal import (
    day_of_week,
    hour_sin_cos,
    is_weekend,
    is_within_typical_hours,
    minutes_off_typical_midshift,
)


class FeatureExtractor:
    """
    Stateful feature extractor.

    Use:
        extractor = FeatureExtractor(topology=..., baselines=...)
        for row_dict in extractor.extract_iter(events):
            ...

    Or as a one-shot:
        df = extractor.extract_dataframe(events)
    """

    def __init__(
        self,
        *,
        topology: BuildingTopology,
        baselines: BaselineCatalog,
    ) -> None:
        self._topo = topology
        self._catalog = baselines
        self._zone_idx = topology.zone_index()
        self._user_idx = topology.user_index()
        self._freq = FrequencyState()

    def reset(self) -> None:
        """Clear the sliding-window state. Use between independent passes."""
        self._freq = FrequencyState()

    # -------------------------------------------------------------------------
    # Streaming API
    # -------------------------------------------------------------------------

    def extract_iter(
        self, events: Iterable[UnifiedEvent]
    ) -> Iterator[dict]:
        """
        Yield one feature dict per event. Updates internal state.
        """
        for ev in events:
            yield self._extract_one(ev)
            # Update the frequency state AFTER computing features for this
            # event, so the counts reflect events strictly before the current
            # one. This avoids self-reference (an event counting itself in
            # its own "events_user_last_1h" feature).
            self._freq.observe(ev)

    def _extract_one(self, event: UnifiedEvent) -> dict:
        user = (
            self._user_idx.get(event.user_id)
            if event.user_id is not None
            else None
        )
        zone = self._zone_idx.get(event.zone_id)
        h_sin, h_cos = hour_sin_cos(event)

        # Network needs a small extra step: if BADGE_ACCESS, we need badge_id
        # for the DENIED-by-badge tracking.
        badge_id: Optional[str] = None
        if event.event_type == EventType.BADGE_ACCESS:
            payload = event.payload
            if isinstance(payload, BadgeAccessPayload):
                badge_id = payload.badge_id

        row = {
            # ---- identity ----
            "event_id": str(event.event_id),
            "timestamp": event.timestamp,
            "event_type": event.event_type.value,
            "source_layer": event.source_layer.value,
            "zone_id": event.zone_id,
            "device_id": event.device_id,
            "user_id": event.user_id if event.user_id is not None else None,

            # ---- temporal ----
            "hour_sin": h_sin,
            "hour_cos": h_cos,
            "day_of_week": day_of_week(event),
            "is_weekend": is_weekend(event),
            "is_within_typical_hours": is_within_typical_hours(event, user),
            "minutes_off_typical_midshift":
                minutes_off_typical_midshift(event, user),

            # ---- spatial ----
            "zone_sensitivity_lvl": zone_sensitivity_lvl(zone),
            "is_typical_zone_for_user": is_typical_zone_for_user(event, user),
            "entity_count": (
                float(event.payload.entity_count)
                if isinstance(event.payload, MotionDetectedPayload)
                else float("nan")
            ),

            # ---- frequency (using state BEFORE this event) ----
            "events_user_last_1h": self._freq.events_for_user(
                event.user_id, event.timestamp, WINDOW_1H
            ),
            "events_user_last_24h": self._freq.events_for_user(
                event.user_id, event.timestamp, WINDOW_24H
            ),
            "events_zone_last_5min": self._freq.events_for_zone(
                event.zone_id, event.timestamp, WINDOW_5MIN
            ),
            "events_zone_last_1h": self._freq.events_for_zone(
                event.zone_id, event.timestamp, WINDOW_1H
            ),
            "denied_badges_user_last_5min": self._freq.denied_for_user(
                event.user_id, badge_id, event.timestamp, WINDOW_5MIN
            ),
            "denied_badges_zone_last_5min": self._freq.denied_for_zone(
                event.zone_id, event.timestamp, WINDOW_5MIN
            ),

            # ---- network ----
            **network_features(event, self._catalog),
        }
        return row

    # -------------------------------------------------------------------------
    # Batch API
    # -------------------------------------------------------------------------

    def extract_dataframe(
        self, events: Iterable[UnifiedEvent]
    ) -> pd.DataFrame:
        """
        Run the extractor on a (finite) iterable of events and return a
        DataFrame conforming to the canonical schema.
        """
        rows = list(self.extract_iter(events))
        df = pd.DataFrame.from_records(rows, columns=COLUMN_NAMES)
        return coerce_dataframe(df)