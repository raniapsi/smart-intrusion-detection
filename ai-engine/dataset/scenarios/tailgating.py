"""
Scenario 3 — Tailgating (one badge, two people through).

A legitimate user badges into Z2 (open office) but TWO people walk in:
the badge holder and an unauthorised person following close behind.
Detected when motion sensor reports entity_count >= 2 within seconds
of a single badge event.

Discriminant time: morning rush (08:30-09:30) when many people enter
and a tailgater can blend in.

Expected classification: SUSPECT (~0.60 per README section 12).
The badge itself is legitimate; only the motion mismatch betrays it.
"""

from __future__ import annotations

from datetime import date, time

from schemas import AccessResult, AIClassification, BuildingTopology, UnifiedEvent

from ..generators.badge import make_badge_event
from ..generators.door import make_door_closed_event, make_door_opened_event
from ..generators.motion import make_motion_event
from ..generators.rng import Rng
from ..generators.timeline import at_offset, combine_utc
from .base import (
    InjectionResult,
    Scenario,
    Truth,
    find_door_to_zone,
    merge_and_sort,
)


class TailgatingScenario(Scenario):
    name = "tailgating"
    default_day = "2026-04-08"  # Wednesday morning

    ATTACK_HOUR = 8
    ATTACK_MINUTE = 47
    TARGET_ZONE = "Z2"  # Open Office
    TARGET_USER = "u012"

    def inject(
        self,
        *,
        baseline: list[UnifiedEvent],
        topo: BuildingTopology,
        rng: Rng,
    ) -> InjectionResult:
        if baseline:
            d: date = baseline[0].timestamp.date()
        else:
            d = date.fromisoformat(self.default_day)

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 12))

        user = topo.user_index().get(self.TARGET_USER) or topo.users[0]
        door = find_door_to_zone(topo, self.TARGET_ZONE)
        from schemas import DeviceType
        reader_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.BADGE_READER),
            None,
        )
        if reader_id is None or door is None or door.sensor_device_id is None:
            raise RuntimeError(
                f"tailgating needs reader+door+sensor in {self.TARGET_ZONE}"
            )
        md_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.MOTION_DETECTOR),
            None,
        )

        attack_events: list[UnifiedEvent] = []

        # 1) Single legitimate badge access
        badge = make_badge_event(
            timestamp=attack_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            reader_device_id=reader_id,
            badge_id=user.badge_id,
            user_id=user.user_id,
            access_result=AccessResult.GRANTED,
            door_id=door.door_id,
        )
        attack_events.append(badge)

        # 2) Door opens
        open_ts = at_offset(attack_ts, 0.5)
        attack_events.append(make_door_opened_event(
            timestamp=open_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            associated_badge_event_id=badge.event_id,
        ))

        # 3) Motion detector reports TWO entities — the tailgating signal
        if md_id is not None:
            attack_events.append(make_motion_event(
                timestamp=at_offset(open_ts, 1.5),
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                detector_device_id=md_id,
                entity_count=2,
            ))

        # 4) Door closes after a slightly longer hold (someone holding it open)
        attack_events.append(make_door_closed_event(
            timestamp=at_offset(open_ts, 7.5),
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            open_duration_seconds=7.5,
        ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"User {user.user_id} badged into {self.TARGET_ZONE} but the "
                "motion sensor detected 2 entities in the same window — "
                "tailgating signal."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, 15.0),
            target_zone=self.TARGET_ZONE,
            target_user=user.user_id,
            expected_classification=AIClassification.SUSPECT,
            expected_min_score=0.45,
            expected_detectors=["rule:tailgating"],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )