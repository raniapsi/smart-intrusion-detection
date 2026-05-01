"""
Scenario 7 — Credential theft / abuse after legitimate physical access.

A user (whose credentials have been stolen) badges into an office area
during normal hours. Everything looks fine on the physical side: badge
GRANTED, motion of one person, door closed normally.

But within 60 seconds, traffic from a workstation (modelled as the
zone's camera, simplification) spikes to an unusual EXTERNAL destination
with high outbound volume — the attacker is exfiltrating from inside.

Discriminant: post-access cyber anomaly correlated with the badge event.
The badge alone is normal. The cyber alone is suspicious. Together they
are a clear pattern.

Expected classification: CRITICAL (~0.85 per README section 12).
This is the test case for the fusion scorer + correlation engine.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from schemas import (
    AccessResult,
    AIClassification,
    BuildingTopology,
    EventType,
    NetworkAnomalyLabel,
    NetworkAnomalyPayload,
    NetworkFlowPayload,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
)

from ..generators.badge import make_badge_event
from ..generators.door import make_door_closed_event, make_door_opened_event
from ..generators.motion import make_motion_event
from ..generators.rng import Rng
from ..generators.timeline import at_offset, combine_utc
from .base import (
    InjectionResult,
    Scenario,
    Truth,
    find_camera_in_zone,
    find_door_to_zone,
    merge_and_sort,
)


class CredentialTheftScenario(Scenario):
    name = "credential_theft"
    default_day = "2026-04-08"  # Wednesday afternoon

    ATTACK_HOUR = 15
    ATTACK_MINUTE = 22
    TARGET_ZONE = "Z4"  # Engineering — has cameras and is plausible target
    TARGET_USER = "u020"
    EXFIL_DURATION_MINUTES = 4

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

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 0))

        user = topo.user_index().get(self.TARGET_USER) or topo.users[0]
        door = find_door_to_zone(topo, self.TARGET_ZONE)
        cam_id = find_camera_in_zone(topo, self.TARGET_ZONE)
        from schemas import DeviceType
        reader_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.BADGE_READER),
            None,
        )
        md_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.MOTION_DETECTOR),
            None,
        )
        if reader_id is None or door is None or door.sensor_device_id is None:
            raise RuntimeError(
                f"credential_theft needs reader+door in {self.TARGET_ZONE}"
            )
        if cam_id is None:
            raise RuntimeError(
                f"credential_theft needs a camera in {self.TARGET_ZONE}"
            )
        cam_dev = next(d for d in topo.devices if d.device_id == cam_id)
        cam_ip = cam_dev.ip_address or "10.0.10.99"

        attack_events: list[UnifiedEvent] = []

        # ---- Phase 1: legitimate-looking physical access ----
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

        open_ts = at_offset(attack_ts, 0.5)
        attack_events.append(make_door_opened_event(
            timestamp=open_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            associated_badge_event_id=badge.event_id,
        ))
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

        # ---- Phase 2: post-access exfiltration ----
        # Starts ~60s after the badge — the attacker is now inside and
        # uses a workstation to exfiltrate. We model traffic from the
        # zone's camera as a proxy (in 2c+ we could add NETWORK_FLOW
        # from individual workstations, but the camera shortcut is enough
        # to test the correlation scoring).
        exfil_start = at_offset(attack_ts, 60.0)
        for i in range(self.EXFIL_DURATION_MINUTES):
            t = exfil_start + timedelta(seconds=i * 60.0 + 30.0)
            attack_events.append(UnifiedEvent(
                event_type=EventType.NETWORK_FLOW,
                source_layer=SourceLayer.CYBER,
                timestamp=t,
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                device_id=cam_id,
                user_id=None,
                severity_raw=SeverityRaw.WARNING,
                payload=NetworkFlowPayload(
                    src_ip=cam_ip,
                    dst_ip="198.51.100.42",      # external attacker host
                    bytes_out=int(rng.lognormal(13.0, 0.4)),  # large outbound
                    bytes_in=int(rng.lognormal(6.5, 0.3)),
                    distinct_dst_ports=int(rng.poisson(1.5)) + 1,
                    window_seconds=60.0,
                ),
            ))

        # Explicit anomaly marker midway through exfiltration
        midpoint = exfil_start + timedelta(seconds=self.EXFIL_DURATION_MINUTES * 30.0)
        attack_events.append(UnifiedEvent(
            event_type=EventType.NETWORK_ANOMALY,
            source_layer=SourceLayer.CYBER,
            timestamp=midpoint,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            device_id=cam_id,
            user_id=None,
            severity_raw=SeverityRaw.ALERT,
            payload=NetworkAnomalyPayload(
                anomaly_label=NetworkAnomalyLabel.EXFILTRATION,
                src_ip=cam_ip,
                severity_hint=0.75,
            ),
        ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"User {user.user_id} badged legitimately into {self.TARGET_ZONE} "
                f"at {attack_ts.time()} UTC. Within 60s, exfiltration traffic "
                f"started from the zone for {self.EXFIL_DURATION_MINUTES} minutes "
                "to an external IP — credentials likely stolen."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, 60.0 + self.EXFIL_DURATION_MINUTES * 60.0),
            target_zone=self.TARGET_ZONE,
            target_user=user.user_id,
            expected_classification=AIClassification.CRITICAL,
            expected_min_score=0.80,
            expected_detectors=[
                "if:network_volume",
                "rule:exfiltration",
                "fusion:phys_cyber_corr",
            ],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )