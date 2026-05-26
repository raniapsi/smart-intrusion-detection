"""
Multi-user, multi-day orchestrator.

Composes the per-user-day generator and the network flow generator into a
full dataset:

  for each day in range:
      events_today = []
      for each user:
          user_events = generate_user_day(...)
          events_today.extend(user_events)
      presence_intervals = derive_presence_intervals(events_today)
      events_today.extend(generate_network_flows_for_day(...))
      events_today.sort(by timestamp)
      yield events_today

The orchestrator is also responsible for:
  - skipping weekends (no user activity, but cameras DO still emit at
    night-baseline traffic — included so attack scenarios on weekends
    are plausible later)
  - deriving presence intervals from the user events (which zone is each
    user in, at what time)
  - sorting all events by timestamp before yielding

Output: an iterator of UnifiedEvent. The CLI writes them to a single
global JSONL file.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterator

from schemas import (
    AccessResult,
    BuildingTopology,
    EventType,
    UnifiedEvent,
)

from .network import generate_network_flows_for_day
from .rng import Rng
from .timeline import UTC, combine_utc, is_weekend
from .user_day import generate_user_day


# How long a user is assumed to stay in a zone after the last badge of the
# day, before "departing". Defensive default for cases where we can't see
# an explicit exit. With the user_day generator, the last event is always
# a return to Z1 (lobby) so this rarely matters, but it keeps the presence
# intervals well-formed.
DEFAULT_TRAILING_SECONDS = 300.0


def _derive_presence_intervals(
    events: list[UnifiedEvent],
    day_end: datetime,
) -> dict[str, list[tuple[datetime, datetime]]]:
    """
    Reconstruct, from a sorted list of events, when each zone had a user.

    Algorithm: for each user, we walk their granted-badge events in time
    order. Each badge access marks an entry into the badged zone. The user
    is considered present in that zone until their NEXT badge access (which
    moves them to a new zone), or until day_end if there is no next.

    Returns: zone_id -> list of (start, end) intervals during which AT LEAST
    ONE user was in the zone. Multiple users in the same zone produce
    overlapping intervals — the network generator counts them by summing
    overlaps, which gives the user count at any timestamp.
    """
    # Group granted-badge events per user, in chronological order.
    per_user: dict[str, list[UnifiedEvent]] = {}
    for ev in events:
        if (
            ev.event_type == EventType.BADGE_ACCESS
            and ev.user_id is not None
            and ev.payload.access_result == AccessResult.GRANTED
        ):
            per_user.setdefault(ev.user_id, []).append(ev)
    for lst in per_user.values():
        lst.sort(key=lambda e: e.timestamp)

    intervals: dict[str, list[tuple[datetime, datetime]]] = {}
    for user_id, badges in per_user.items():
        for i, badge in enumerate(badges):
            start = badge.timestamp
            if i + 1 < len(badges):
                end = badges[i + 1].timestamp
            else:
                # No further badge for this user today — give a short tail.
                end = min(
                    badge.timestamp + timedelta(seconds=DEFAULT_TRAILING_SECONDS),
                    day_end,
                )
            if end <= start:
                continue
            intervals.setdefault(badge.zone_id, []).append((start, end))

    return intervals


def generate_day(
    *,
    topo: BuildingTopology,
    day: date,
    rng: Rng,
) -> list[UnifiedEvent]:
    """
    Generate all events for one day across all users + the network layer.

    The list is sorted by timestamp before being returned.
    """
    day_rng = rng.derive("day", day.isoformat())
    day_start = combine_utc(day, datetime.min.time())
    day_end = combine_utc(day + timedelta(days=1), datetime.min.time())

    events: list[UnifiedEvent] = []

    # 1) User events (skipped on weekends — empty list)
    if not is_weekend(day):
        for user in topo.users:
            user_rng = day_rng.derive("user", user.user_id)
            events.extend(
                generate_user_day(
                    profile=user, topo=topo, day=day, rng=user_rng
                )
            )

    # 2) Presence intervals derived from user events (empty on weekends)
    presence = _derive_presence_intervals(events, day_end)

    # 3) Network layer: cameras emit even on weekends (heartbeat continues)
    net_rng = day_rng.derive("network")
    events.extend(
        generate_network_flows_for_day(
            topo=topo,
            day_start=day_start,
            day_end=day_end,
            presence_intervals=presence,
            rng=net_rng,
        )
    )

    events.sort(key=lambda e: e.timestamp)
    return events


def generate_baseline(
    *,
    topo: BuildingTopology,
    start_day: date,
    n_days: int,
    seed: int,
) -> Iterator[UnifiedEvent]:
    """
    Generate a multi-day baseline dataset.

    Yields events one at a time, globally sorted by timestamp across days.
    (Inside a single day, events are sorted; days are processed in order.)

    Args:
        topo: building topology
        start_day: first day to generate
        n_days: total number of days (calendar days, including weekends)
        seed: master seed for full reproducibility
    """
    root_rng = Rng(seed=seed)
    for offset in range(n_days):
        d = start_day + timedelta(days=offset)
        for ev in generate_day(topo=topo, day=d, rng=root_rng):
            yield ev
