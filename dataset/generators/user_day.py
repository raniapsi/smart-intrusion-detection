"""
Generate one user's events for one day.

The story we tell:
  1. Arrival around the user's typical_arrival time (gaussian).
  2. The user enters at the lobby (Z1), then walks through Z2 (open office)
     to reach their typical zones.
  3. Through the day they make a few inter-zone moves, weighted by their
     typical_zones list.
  4. Departure around their typical_departure time (gaussian).

For each transition between zones, we emit:
  - BADGE_ACCESS (granted) on the destination zone's reader
  - DOOR_OPENED a fraction of a second later
  - DOOR_CLOSED a few seconds later
  - MOTION_DETECTED in the destination zone (if it has a motion sensor)

Weekends produce no events (closed building).

This module is INTENTIONALLY simple in 2a. The 2b version will add:
  - more elaborate movement patterns (lunch, meetings, etc.)
  - background motion events from cleaning staff / HVAC
  - network flow events tied to the user's presence
"""

from __future__ import annotations

from datetime import date, time
from typing import Iterator, Optional

from schemas import (
    AccessResult,
    BuildingTopology,
    DeviceType,
    UnifiedEvent,
    UserProfile,
    Zone,
    ZoneSensitivity,
)

from .badge import make_badge_event
from .door import make_door_closed_event, make_door_opened_event
from .motion import make_motion_event
from .rng import Rng
from .timeline import (
    UTC,
    at_offset,
    combine_utc,
    is_weekend,
    seconds_to_time,
    time_of_day_seconds,
)


# -----------------------------------------------------------------------------
# Tunable parameters (kept here, not buried in the topology YAML)
# -----------------------------------------------------------------------------

# Mean number of intermediate zone moves during the day (Poisson lambda).
# A user does arrival + this many moves + departure.
MEAN_MIDDAY_MOVES = 4.0

# Mean and std of the time the door stays open (seconds).
DOOR_OPEN_DURATION_MEAN = 4.5
DOOR_OPEN_DURATION_STD = 1.2

# Delay between badge-granted and door-opened (seconds).
BADGE_TO_DOOR_OPEN_MEAN = 0.4
BADGE_TO_DOOR_OPEN_STD = 0.15

# Small jitter so motion is detected slightly after door open.
DOOR_OPEN_TO_MOTION_MEAN = 1.5
DOOR_OPEN_TO_MOTION_STD = 0.5

# Probability a granted-badge event is followed by a DENIED retry
# (e.g. user mistakenly badges twice). Kept in baseline so the AI sees it.
P_DUPLICATE_BADGE_DENIED = 0.02


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _door_for_zone(topo: BuildingTopology, zone_id: str):
    """Return the first Door object whose `zone_id` matches, or None."""
    for door in topo.doors:
        if door.zone_id == zone_id:
            return door
    return None


def _motion_detector_for_zone(topo: BuildingTopology, zone_id: str):
    """Return the first motion-detector device in this zone, or None."""
    for dev in topo.devices:
        if dev.zone_id == zone_id and dev.type == DeviceType.MOTION_DETECTOR:
            return dev
    return None


def _reader_for_zone(topo: BuildingTopology, zone_id: str):
    """Return the first badge reader in this zone, or None."""
    for dev in topo.devices:
        if dev.zone_id == zone_id and dev.type == DeviceType.BADGE_READER:
            return dev
    return None


def _sample_arrival_seconds(profile: UserProfile, rng: Rng) -> float:
    """Sample an arrival time as seconds-since-midnight, gaussian around typical."""
    mean_s = time_of_day_seconds(profile.typical_arrival)
    std_s = profile.arrival_std_minutes * 60.0
    s = rng.normal(mean_s, std_s)
    # Clamp to a sensible window [00:00, 23:59:59] and ensure positive.
    return max(0.0, min(s, 86399.0))


def _sample_departure_seconds(
    profile: UserProfile, rng: Rng, after_seconds: float
) -> float:
    """Sample a departure time, gaussian around typical, never before `after_seconds`."""
    mean_s = time_of_day_seconds(profile.typical_departure)
    std_s = profile.departure_std_minutes * 60.0
    s = rng.normal(mean_s, std_s)
    # Departure must be after the last in-day event by at least 60 seconds.
    return max(after_seconds + 60.0, min(s, 86399.0))


def _pick_destination_zone(
    profile: UserProfile,
    topo: BuildingTopology,
    current_zone_id: str,
    rng: Rng,
) -> Optional[Zone]:
    """
    Pick a destination zone among the user's typical zones, excluding
    the current zone. Returns None if no valid candidate.
    """
    candidates = [
        zid for zid in profile.typical_zones if zid != current_zone_id
    ]
    if not candidates:
        return None
    chosen_id = rng.choice(candidates)
    return topo.zone_index().get(chosen_id)


# -----------------------------------------------------------------------------
# Main orchestration
# -----------------------------------------------------------------------------

def _emit_zone_entry(
    *,
    profile: UserProfile,
    topo: BuildingTopology,
    target_zone: Zone,
    badge_timestamp_seconds: float,
    day: date,
    rng: Rng,
) -> Iterator[UnifiedEvent]:
    """
    Emit the cluster of events that represent a user entering a zone:
    badge granted -> (rare) duplicate denied -> door opened -> motion -> door closed.

    `badge_timestamp_seconds` is seconds-since-midnight UTC of the badge scan.
    """
    reader = _reader_for_zone(topo, target_zone.zone_id)
    if reader is None:
        # Nothing to emit if the target zone has no reader. Should not happen
        # in our topologies but we keep the generator robust.
        return

    door = _door_for_zone(topo, target_zone.zone_id)

    badge_ts = combine_utc(day, seconds_to_time(badge_timestamp_seconds))

    # 1) BADGE_ACCESS granted
    badge_evt = make_badge_event(
        timestamp=badge_ts,
        building_id=topo.building_id,
        zone_id=target_zone.zone_id,
        reader_device_id=reader.device_id,
        badge_id=profile.badge_id,
        user_id=profile.user_id,
        access_result=AccessResult.GRANTED,
        door_id=door.door_id if door is not None else None,
    )
    yield badge_evt

    # 2) Occasional duplicate badge that gets denied (real-world noise)
    if rng.bernoulli(P_DUPLICATE_BADGE_DENIED):
        dup_offset = rng.uniform(0.5, 1.5)
        yield make_badge_event(
            timestamp=at_offset(badge_ts, dup_offset),
            building_id=topo.building_id,
            zone_id=target_zone.zone_id,
            reader_device_id=reader.device_id,
            badge_id=profile.badge_id,
            user_id=profile.user_id,
            access_result=AccessResult.DENIED,
            door_id=door.door_id if door is not None else None,
        )

    # 3) DOOR_OPENED (only if the zone has a door + sensor)
    if door is not None and door.sensor_device_id is not None:
        door_open_offset = max(
            0.05,
            rng.normal(BADGE_TO_DOOR_OPEN_MEAN, BADGE_TO_DOOR_OPEN_STD),
        )
        door_open_ts = at_offset(badge_ts, door_open_offset)
        yield make_door_opened_event(
            timestamp=door_open_ts,
            building_id=topo.building_id,
            zone_id=target_zone.zone_id,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            associated_badge_event_id=badge_evt.event_id,
        )

        # 4) MOTION_DETECTED shortly after entry, if the zone has one
        detector = _motion_detector_for_zone(topo, target_zone.zone_id)
        if detector is not None:
            motion_offset = max(
                0.1,
                rng.normal(DOOR_OPEN_TO_MOTION_MEAN, DOOR_OPEN_TO_MOTION_STD),
            )
            yield make_motion_event(
                timestamp=at_offset(door_open_ts, motion_offset),
                building_id=topo.building_id,
                zone_id=target_zone.zone_id,
                detector_device_id=detector.device_id,
                entity_count=1,
            )

        # 5) DOOR_CLOSED a few seconds after open
        open_duration = max(
            0.5, rng.normal(DOOR_OPEN_DURATION_MEAN, DOOR_OPEN_DURATION_STD)
        )
        yield make_door_closed_event(
            timestamp=at_offset(door_open_ts, open_duration),
            building_id=topo.building_id,
            zone_id=target_zone.zone_id,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            open_duration_seconds=open_duration,
        )


def generate_user_day(
    *,
    profile: UserProfile,
    topo: BuildingTopology,
    day: date,
    rng: Rng,
) -> list[UnifiedEvent]:
    """
    Generate all events for one user during one day.

    Returns a list of events sorted by timestamp.
    Returns an empty list on weekends.
    """
    if is_weekend(day):
        return []

    # Derive a per-day RNG so re-running this user on a different day
    # uses an independent stream.
    day_rng = rng.derive("day", day.isoformat())

    events: list[UnifiedEvent] = []

    # ---- Arrival -----------------------------------------------------------
    arrival_s = _sample_arrival_seconds(profile, day_rng)

    # The user enters the building at Z1 (lobby). Find Z1; if absent, fall
    # back to the user's first typical zone.
    z1 = topo.zone_index().get("Z1")
    entry_zone = z1 if z1 is not None else topo.zone_index()[profile.typical_zones[0]]

    events.extend(
        _emit_zone_entry(
            profile=profile,
            topo=topo,
            target_zone=entry_zone,
            badge_timestamp_seconds=arrival_s,
            day=day,
            rng=day_rng.derive("entry"),
        )
    )

    current_zone_id = entry_zone.zone_id
    last_event_seconds = arrival_s

    # ---- Mid-day moves ------------------------------------------------------
    n_moves = day_rng.poisson(MEAN_MIDDAY_MOVES)
    # Spread the moves between arrival+30min and departure-30min.
    departure_target = time_of_day_seconds(profile.typical_departure)
    work_window_start = arrival_s + 30 * 60
    work_window_end = max(work_window_start + 60, departure_target - 30 * 60)

    for i in range(n_moves):
        move_rng = day_rng.derive("move", str(i))
        # Uniform-ish distribution of moves through the work window.
        move_s = move_rng.uniform(work_window_start, work_window_end)
        # Ensure monotonicity: a move can't happen before the previous one.
        move_s = max(move_s, last_event_seconds + 30.0)
        if move_s >= 86399.0:
            break

        dest = _pick_destination_zone(
            profile, topo, current_zone_id, move_rng
        )
        if dest is None:
            break

        new_events = list(
            _emit_zone_entry(
                profile=profile,
                topo=topo,
                target_zone=dest,
                badge_timestamp_seconds=move_s,
                day=day,
                rng=move_rng,
            )
        )
        events.extend(new_events)
        current_zone_id = dest.zone_id
        last_event_seconds = move_s

    # ---- Departure ----------------------------------------------------------
    # Modelled as a final badge at the lobby (zone Z1) on the way out.
    departure_s = _sample_departure_seconds(
        profile, day_rng.derive("departure"), last_event_seconds
    )
    if departure_s < 86399.0:
        events.extend(
            _emit_zone_entry(
                profile=profile,
                topo=topo,
                target_zone=entry_zone,
                badge_timestamp_seconds=departure_s,
                day=day,
                rng=day_rng.derive("exit"),
            )
        )

    # Sort by timestamp; the generators emit roughly in order but small
    # negative offsets (e.g. duplicate denied) may shift things slightly.
    events.sort(key=lambda e: e.timestamp)
    return events
