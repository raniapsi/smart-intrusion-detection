"""
Network flow event generator.

Model:
  - Each camera emits one NETWORK_FLOW event every WINDOW_SECONDS (default 60s),
    24/7. This is the "heartbeat" — devices are always talking, even at night.
  - Volumes follow a lognormal distribution (heavy-tailed: realistic for
    network traffic) with per-device baselines drawn at startup.
  - A diurnal multiplier increases traffic during daytime (8h-19h UTC).
  - A presence multiplier boosts traffic when at least one user is in the
    camera's zone — modelling the camera's CV pipeline pushing more frames.
  - Distinct destination ports stay tight in baseline (1-4 per window).
    Attack scenarios in 2c will inflate this to dozens (port scan signal).

The generator is a function that, given a TIME-WINDOWED VIEW of user
presence, emits all flow events for that window. The caller (orchestrator)
provides the presence map.

This file is INTENTIONALLY independent of user_day.py: orchestrator builds
the presence map by replaying user days, then calls this for the network
layer. Keeps responsibilities clear.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from schemas import (
    BuildingTopology,
    Device,
    DeviceType,
    EventType,
    NetworkFlowPayload,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
)

from .rng import Rng


# -----------------------------------------------------------------------------
# Tunable parameters
# -----------------------------------------------------------------------------

# Window between consecutive flow events per device.
WINDOW_SECONDS: float = 60.0

# Lognormal parameters for baseline traffic (in bytes).
# A draw of lognormal(mu, sigma) with mu=10.5, sigma=0.5 gives roughly
# 36 KB median, with a heavy tail up to a few hundred KB. Realistic for
# a camera periodic upload.
BASELINE_OUT_LOGMEAN: float = 10.5
BASELINE_OUT_LOGSIGMA: float = 0.5
BASELINE_IN_LOGMEAN: float = 8.5    # less inbound than outbound for a camera
BASELINE_IN_LOGSIGMA: float = 0.4

# Diurnal multiplier: 1.0 at night, 2.0 during day.
DAY_START_HOUR: int = 8
DAY_END_HOUR: int = 19
DIURNAL_MULTIPLIER_DAY: float = 2.0
DIURNAL_MULTIPLIER_NIGHT: float = 1.0

# Per-user-present multiplier: a camera with N users in its zone sees
# more activity. We use 1.0 + 0.4 * N, capped at 3.0 (a crowded room
# doesn't 10x the camera's bandwidth — there's an asymptote).
PER_USER_BOOST: float = 0.4
PER_USER_CAP: float = 3.0

# Distinct ports in baseline: low (1-4), Poisson-ish.
BASELINE_PORTS_LAMBDA: float = 1.5  # mean ~1.5, mostly 1-3, rarely 4-5


# -----------------------------------------------------------------------------
# Per-device baseline parameters
# -----------------------------------------------------------------------------

class _DeviceBaseline:
    """
    Per-device baseline parameters.

    Each camera has slightly different "personality": a few percent
    variation around the global lognormal centres, so the AI can learn
    per-device profiles in addition to the global one.
    """

    __slots__ = ("device_id", "ip_address", "out_logmean", "out_logsigma",
                 "in_logmean", "in_logsigma", "dst_ip")

    def __init__(self, device: Device, rng: Rng):
        self.device_id = device.device_id
        self.ip_address = device.ip_address or "10.0.10.0"
        # Each camera's mean shifts by up to +/- 0.15 in log-space (~+/-15%).
        self.out_logmean = BASELINE_OUT_LOGMEAN + rng.uniform(-0.15, 0.15)
        self.out_logsigma = BASELINE_OUT_LOGSIGMA
        self.in_logmean = BASELINE_IN_LOGMEAN + rng.uniform(-0.15, 0.15)
        self.in_logsigma = BASELINE_IN_LOGSIGMA
        # Cameras typically push to a single backend recorder; we model that.
        self.dst_ip = "10.0.20.1"


def build_camera_baselines(
    topo: BuildingTopology, rng: Rng
) -> dict[str, _DeviceBaseline]:
    """One baseline per camera in the topology."""
    baselines: dict[str, _DeviceBaseline] = {}
    for dev in topo.devices:
        if dev.type == DeviceType.CAMERA:
            sub = rng.derive("cam-baseline", dev.device_id)
            baselines[dev.device_id] = _DeviceBaseline(dev, sub)
    return baselines


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _diurnal_multiplier(t: datetime) -> float:
    """Day vs night multiplier."""
    h = t.hour
    if DAY_START_HOUR <= h < DAY_END_HOUR:
        return DIURNAL_MULTIPLIER_DAY
    return DIURNAL_MULTIPLIER_NIGHT


def _presence_multiplier(n_users: int) -> float:
    """Boost from N users currently in the zone."""
    return min(PER_USER_CAP, 1.0 + PER_USER_BOOST * n_users)


# -----------------------------------------------------------------------------
# Main generator
# -----------------------------------------------------------------------------

def generate_camera_flow(
    *,
    topo: BuildingTopology,
    baseline: _DeviceBaseline,
    zone_id: str,
    timestamp: datetime,
    n_users_in_zone: int,
    rng: Rng,
) -> UnifiedEvent:
    """
    One NETWORK_FLOW event for one camera at one timestamp.

    The volumes are sampled from lognormal centred on the device's baseline,
    multiplied by the diurnal and presence factors.
    """
    diurnal = _diurnal_multiplier(timestamp)
    presence = _presence_multiplier(n_users_in_zone)
    factor = diurnal * presence

    out_bytes = int(rng.lognormal(baseline.out_logmean, baseline.out_logsigma) * factor)
    in_bytes = int(rng.lognormal(baseline.in_logmean, baseline.in_logsigma) * factor)
    n_ports = max(1, rng.poisson(BASELINE_PORTS_LAMBDA))

    return UnifiedEvent(
        event_type=EventType.NETWORK_FLOW,
        source_layer=SourceLayer.CYBER,
        timestamp=timestamp,
        building_id=topo.building_id,
        zone_id=zone_id,
        device_id=baseline.device_id,
        user_id=None,  # network flows are not attributed to users
        severity_raw=SeverityRaw.INFO,
        payload=NetworkFlowPayload(
            src_ip=baseline.ip_address,
            dst_ip=baseline.dst_ip,
            bytes_out=out_bytes,
            bytes_in=in_bytes,
            distinct_dst_ports=n_ports,
            window_seconds=WINDOW_SECONDS,
        ),
    )


def generate_network_flows_for_day(
    *,
    topo: BuildingTopology,
    day_start: datetime,
    day_end: datetime,
    presence_intervals: dict[str, list[tuple[datetime, datetime]]],
    rng: Rng,
) -> Iterable[UnifiedEvent]:
    """
    Generate all NETWORK_FLOW events for one day, one event per camera per
    WINDOW_SECONDS.

    Args:
        topo: building topology
        day_start, day_end: tz-aware UTC bounds of the day to generate
        presence_intervals: zone_id -> list of (start, end) intervals during
            which AT LEAST ONE user was present in that zone. Used to count
            n_users_in_zone at any sample point.
        rng: derived RNG for this day, used to sample volumes.

    The presence_intervals can be approximate: we count how many intervals
    contain `t` to estimate the user count. This is fast and good enough for
    a baseline model.
    """
    baselines = build_camera_baselines(topo, rng.derive("baseline-init"))

    cameras = [d for d in topo.devices if d.type == DeviceType.CAMERA]
    for cam in cameras:
        cam_baseline = baselines[cam.device_id]
        cam_rng = rng.derive("cam", cam.device_id)
        intervals = presence_intervals.get(cam.zone_id, [])

        t = day_start
        slot_idx = 0
        while t < day_end:
            n_users = sum(
                1 for (start, end) in intervals if start <= t < end
            )
            slot_rng = cam_rng.derive("slot", str(slot_idx))
            yield generate_camera_flow(
                topo=topo,
                baseline=cam_baseline,
                zone_id=cam.zone_id,
                timestamp=t,
                n_users_in_zone=n_users,
                rng=slot_rng,
            )
            t = t + timedelta(seconds=WINDOW_SECONDS)
            slot_idx += 1
