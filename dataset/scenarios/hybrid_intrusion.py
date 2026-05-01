"""
Scenario 5 — Hybrid physical+cyber intrusion (the showcase scenario).

Two coordinated signals in the same zone within seconds:
  - A door to Z8 (server room) is forced open at 03:17 UTC
  - A few seconds later, the camera in Z8 emits an abnormal NETWORK_FLOW
    with very high distinct_dst_ports (port scan) AND a NETWORK_ANOMALY
    event (PORT_SCAN label) — as if the attacker compromised the camera
    or plugged into its switch port.

This is the "1.0 CRITICAL" example from README section 9 (end-to-end
data flow) and section 12. The fusion scorer should give max score
because correlation between physical and cyber signals fires.

Expected classification: CRITICAL (1.0).
"""

from __future__ import annotations

from datetime import date, time

from schemas import (
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

from ..generators.door import (
    make_door_closed_event,
    make_door_forced_event,
)
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


class HybridIntrusionScenario(Scenario):
    name = "hybrid_intrusion"
    default_day = "2026-04-04"  # Saturday — most discriminant

    ATTACK_HOUR = 3
    ATTACK_MINUTE = 17
    TARGET_ZONE = "Z8"

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

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 42))

        door = find_door_to_zone(topo, self.TARGET_ZONE)
        cam_id = find_camera_in_zone(topo, self.TARGET_ZONE)
        if door is None or door.sensor_device_id is None:
            raise RuntimeError(
                f"hybrid_intrusion needs door+sensor in {self.TARGET_ZONE}"
            )
        if cam_id is None:
            raise RuntimeError(
                f"hybrid_intrusion needs a camera in {self.TARGET_ZONE}"
            )

        # The camera's IP — pull from the Device record.
        cam_dev = next(d for d in topo.devices if d.device_id == cam_id)
        cam_ip = cam_dev.ip_address or "10.0.10.99"

        attack_events: list[UnifiedEvent] = []

        # 1) Forced door (physical signal)
        forced = make_door_forced_event(
            timestamp=attack_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            no_badge_window_seconds=10.0,
        )
        attack_events.append(forced)

        # 2) Motion in zone
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

        # 3) Cyber signal — abnormal NETWORK_FLOW with many ports (port scan)
        scan_ts = at_offset(attack_ts, 3.0)
        attack_events.append(UnifiedEvent(
            event_type=EventType.NETWORK_FLOW,
            source_layer=SourceLayer.CYBER,
            timestamp=scan_ts,
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            device_id=cam_id,
            user_id=None,
            severity_raw=SeverityRaw.WARNING,
            payload=NetworkFlowPayload(
                src_ip=cam_ip,
                dst_ip="10.0.20.1",
                bytes_out=2_000_000,        # ~2 MB outbound — way above baseline ~36 KB
                bytes_in=12_000,
                distinct_dst_ports=47,      # PORT SCAN: dozens of ports vs baseline 1-4
                window_seconds=60.0,
            ),
        ))

        # 4) NETWORK_ANOMALY explicit signal — what the network agent itself flagged
        attack_events.append(UnifiedEvent(
            event_type=EventType.NETWORK_ANOMALY,
            source_layer=SourceLayer.CYBER,
            timestamp=at_offset(scan_ts, 0.5),
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            device_id=cam_id,
            user_id=None,
            severity_raw=SeverityRaw.ALERT,
            payload=NetworkAnomalyPayload(
                anomaly_label=NetworkAnomalyLabel.PORT_SCAN,
                src_ip=cam_ip,
                severity_hint=0.85,
            ),
        ))

        # 5) Door closes after the intrusion completes
        attack_events.append(make_door_closed_event(
            timestamp=at_offset(attack_ts, 90.0),
            building_id=topo.building_id,
            zone_id=self.TARGET_ZONE,
            sensor_device_id=door.sensor_device_id,
            door_id=door.door_id,
            open_duration_seconds=90.0,
        ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"Coordinated intrusion in {self.TARGET_ZONE}: forced door "
                f"at {attack_ts.time()} UTC followed within seconds by a port "
                "scan from the zone's camera (PORT_SCAN, 47 ports). "
                "Physical+cyber correlation expected."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, 120.0),
            target_zone=self.TARGET_ZONE,
            target_user=None,
            expected_classification=AIClassification.CRITICAL,
            expected_min_score=0.95,
            expected_detectors=[
                "rule:door_forced",
                "if:network_volume",
                "rule:port_scan",
                "fusion:phys_cyber_corr",
            ],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )