"""
Scenario 2 — Forced door (no badge in window).

A door to the server room (Z8) is forced open at 03:17 UTC with no
preceding badge access in the 10-second correlation window. This is
the canonical "physical break-in" signal.

Discriminant time: deep night when no legitimate user should be there.
The DOOR_FORCED event itself is high-severity by construction
(severity_raw = ALERT, payload typed DoorForcedPayload).

Expected classification: CRITICAL (~0.80 per README section 12).
A rule-based detector should pick this up immediately even before any
ML scoring.
"""

from __future__ import annotations

from datetime import date, time

from schemas import AIClassification, BuildingTopology, UnifiedEvent

from ..generators.door import (
    make_door_closed_event,
    make_door_forced_event,
    make_door_opened_event,
)
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


class ForcedDoorScenario(Scenario):
    name = "forced_door"
    default_day = "2026-04-04"  # Saturday — most discriminant: nobody around

    ATTACK_HOUR = 3
    ATTACK_MINUTE = 17
    TARGET_ZONE = "Z8"  # Server room (CRITICAL)

    def inject(
        self,
        *,
        baseline: list[UnifiedEvent],
        topo: BuildingTopology,
        rng: Rng,
    ) -> InjectionResult:
        # Use the date carried by any baseline event; if empty (weekend
        # before the network layer ran), fall back to default_day.
        if baseline:
            d: date = baseline[0].timestamp.date()
        else:
            d = date.fromisoformat(self.default_day)

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 42))

        door = find_door_to_zone(topo, self.TARGET_ZONE)
        if door is None or door.sensor_device_id is None:
            raise RuntimeError(
                f"forced_door needs a door + sensor for zone {self.TARGET_ZONE}"
            )

        attack_events: list[UnifiedEvent] = []

        # 1) Forced door event — the critical signal
        forced_evt = make_door_forced_event(
            timestamp=attack_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            no_badge_window_seconds=10.0,
        )
        attack_events.append(forced_evt)

        # 2) Motion detected shortly after entry
        from schemas import DeviceType
        md_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.MOTION_DETECTOR),
            None,
        )
        if md_id is not None:
            attack_events.append(make_motion_event(
                timestamp=at_offset(attack_ts, 2.0),
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                detector_device_id=md_id,
                entity_count=1,
            ))

        # 3) The door eventually closes — emitted as a regular DOOR_CLOSED
        #    a few seconds later. The forced state is captured by the prior
        #    DOOR_FORCED event, not by DOOR_CLOSED.
        attack_events.append(make_door_closed_event(
            timestamp=at_offset(attack_ts, 8.0),
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            open_duration_seconds=8.0,
        ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"Door {door.door_id} to server room {self.TARGET_ZONE} "
                f"forced at {attack_ts.time()} UTC with no badge in window."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, 30.0),
            target_zone=self.TARGET_ZONE,
            target_user=None,
            expected_classification=AIClassification.CRITICAL,
            expected_min_score=0.75,
            expected_detectors=["rule:door_forced"],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )