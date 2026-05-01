"""
Scenario 6 — IoT camera compromise (cyber-only, no physical signal).

A camera (Z7 archives) starts emitting abnormal traffic: high outbound
volume sustained over several minutes, and elevated distinct port count.
There is NO corresponding physical event — the attack came in through
the network.

Discriminant: persistent cyber anomaly with no physical justification.
The AI should NOT correlate with any badge/door event — it should still
score CRITICAL based on the cyber side alone.

Expected classification: CRITICAL (~0.70 per README section 12).
"""

from __future__ import annotations

from datetime import date, time, timedelta

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

from ..generators.rng import Rng
from ..generators.timeline import at_offset, combine_utc
from .base import (
    InjectionResult,
    Scenario,
    Truth,
    find_camera_in_zone,
    merge_and_sort,
)


class CameraCompromiseScenario(Scenario):
    name = "camera_compromise"
    default_day = "2026-04-08"  # Wednesday — anomaly stands out vs busy baseline

    ATTACK_HOUR = 14
    ATTACK_MINUTE = 0
    TARGET_ZONE = "Z7"  # Archives — sensitive but plausible compromise target
    DURATION_MINUTES = 8  # sustained anomaly

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

        cam_id = find_camera_in_zone(topo, self.TARGET_ZONE)
        if cam_id is None:
            raise RuntimeError(f"no camera in {self.TARGET_ZONE}")
        cam_dev = next(d for d in topo.devices if d.device_id == cam_id)
        cam_ip = cam_dev.ip_address or "10.0.10.99"

        # Identify EXISTING baseline NETWORK_FLOW events from this camera in
        # the attack window so we can REPLACE them rather than have duplicates
        # at the same timestamps. We don't actually delete them; instead we
        # add new events that overlap, which is fine for the rules engine
        # (it sees both the legitimate event and the anomalous one) — and
        # arguably more realistic since the camera's normal heartbeat would
        # continue while its bandwidth is being abused.
        # Decision: we just inject our anomalous events; the baseline keeps
        # its own. The AI will see both signals and weight accordingly.

        attack_events: list[UnifiedEvent] = []
        attack_end = attack_ts + timedelta(minutes=self.DURATION_MINUTES)

        # Inject an anomalous NETWORK_FLOW every 60s for the duration
        n_slots = self.DURATION_MINUTES
        for i in range(n_slots):
            t = attack_ts + timedelta(seconds=i * 60.0 + 30.0)  # +30s offset to interleave with baseline
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
                    dst_ip="203.0.113.5",      # external destination — exfiltration target
                    bytes_out=int(rng.lognormal(13.5, 0.3)),  # ~700 KB to a few MB outbound — heavy
                    bytes_in=int(rng.lognormal(7.0, 0.3)),     # tiny inbound (commands)
                    distinct_dst_ports=int(rng.poisson(2.0)) + 1,  # not a port scan, just sustained traffic
                    window_seconds=60.0,
                ),
            ))

        # One explicit NETWORK_ANOMALY event halfway through
        midpoint = at_offset(attack_ts, self.DURATION_MINUTES * 30.0)
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
                f"Camera {cam_id} in zone {self.TARGET_ZONE} emitted sustained "
                f"high-volume outbound traffic to external IP for "
                f"{self.DURATION_MINUTES} minutes — exfiltration via compromised "
                "device, no physical signal."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=attack_end,
            target_zone=self.TARGET_ZONE,
            target_user=None,
            expected_classification=AIClassification.CRITICAL,
            expected_min_score=0.65,
            expected_detectors=["if:network_volume", "rule:exfiltration"],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )