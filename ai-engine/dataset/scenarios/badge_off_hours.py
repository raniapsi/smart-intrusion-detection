"""
Scenario 1 — Badge access outside hours.

A user badges into a sensitive zone (Z7 Archives) at 03:00 UTC, far
outside their typical 9-18 working window. Single anomalous event,
no other signals.

Discriminant time: weekday early morning, when no one else is around.
The AI must pick this up because:
  - timestamp is far outside the user's typical_arrival/departure
  - night-time + restricted zone is a rare combination in baseline
  - no associated lobby badge precedes it (user materialised at Z7)

Expected classification: SUSPECT (~0.55 per README section 12).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from schemas import AccessResult, AIClassification, BuildingTopology, UnifiedEvent

from ..generators.badge import make_badge_event
from ..generators.door import make_door_closed_event, make_door_opened_event
from ..generators.motion import make_motion_event
from ..generators.rng import Rng
from ..generators.timeline import combine_utc, at_offset
from .base import (
    InjectionResult,
    Scenario,
    Truth,
    find_door_to_zone,
    merge_and_sort,
)


class BadgeOffHoursScenario(Scenario):
    name = "badge_off_hours"
    default_day = "2026-04-08"  # Wednesday — there IS baseline traffic to compare against

    # Constants used in this scenario
    ATTACK_HOUR = 3
    ATTACK_MINUTE = 17
    TARGET_ZONE = "Z7"  # Archives (RESTRICTED)
    TARGET_USER = "u005"  # arbitrary employee whose typical hours are 9-18

    def inject(
        self,
        *,
        baseline: list[UnifiedEvent],
        topo: BuildingTopology,
        rng: Rng,
    ) -> InjectionResult:
        # Determine the day from the baseline (they all share the same date).
        if not baseline:
            raise ValueError("badge_off_hours requires a non-empty baseline")
        d: date = baseline[0].timestamp.date()

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 0))

        user = topo.user_index().get(self.TARGET_USER)
        if user is None:
            # Fall back to first user in topology.
            user = topo.users[0]

        door = find_door_to_zone(topo, self.TARGET_ZONE)
        # Even if the user's typical_zones don't include the target, we
        # still emit a GRANTED badge — the system has no per-user permission
        # check (per README "employees only" decision). The anomaly is
        # behavioural, not authorisation.
        from schemas import DeviceType
        reader_id = next(
            (d.device_id for d in topo.devices
             if d.zone_id == self.TARGET_ZONE and d.type == DeviceType.BADGE_READER),
            None,
        )
        if reader_id is None:
            raise RuntimeError(f"no badge reader in zone {self.TARGET_ZONE}")

        attack_events: list[UnifiedEvent] = []

        # 1) Badge granted at 3:17am
        badge = make_badge_event(
            timestamp=attack_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            reader_device_id=reader_id,
            badge_id=user.badge_id,
            user_id=user.user_id,
            access_result=AccessResult.GRANTED,
            door_id=door.door_id if door else None,
        )
        attack_events.append(badge)

        # 2) Door opens, motion, door closes — same as a normal entry.
        if door is not None and door.sensor_device_id is not None:
            open_ts = at_offset(attack_ts, 0.5)
            attack_events.append(make_door_opened_event(
                timestamp=open_ts,
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                sensor_device_id=door.sensor_device_id,
                door_id=door.door_id,
                associated_badge_event_id=badge.event_id,
            ))
            # Motion in the zone
            md_id = next(
                (d.device_id for d in topo.devices
                 if d.zone_id == self.TARGET_ZONE and d.type == DeviceType.MOTION_DETECTOR),
                None,
            )
            if md_id is not None:
                attack_events.append(make_motion_event(
                    timestamp=at_offset(open_ts, 1.5),
                    building_id=topo.building_id,
                    zone_id=self.TARGET_ZONE,
                    detector_device_id=md_id,
                    entity_count=1,
                ))
            attack_events.append(make_door_closed_event(
                timestamp=at_offset(open_ts, 5.0),
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                sensor_device_id=door.sensor_device_id,
                door_id=door.door_id,
                open_duration_seconds=5.0,
            ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"User {user.user_id} badged into restricted zone "
                f"{self.TARGET_ZONE} at {attack_ts.time()} UTC, far outside "
                "the typical 9-18 working window."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, 30.0),
            target_zone=self.TARGET_ZONE,
            target_user=user.user_id,
            expected_classification=AIClassification.SUSPECT,
            expected_min_score=0.45,
            expected_detectors=["if:user_hour", "rule:off_hours_restricted"],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )