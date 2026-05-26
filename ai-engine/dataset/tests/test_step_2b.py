"""
Tests for step 2b — full topology, network generator, multi-day orchestrator.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dataset.generators import (
    Rng,
    build_camera_baselines,
    generate_baseline,
    generate_camera_flow,
    generate_day,
    generate_network_flows_for_day,
    is_weekend,
)
from dataset.generators.network import (
    BASELINE_OUT_LOGMEAN,
    DAY_END_HOUR,
    DAY_START_HOUR,
    DIURNAL_MULTIPLIER_DAY,
    DIURNAL_MULTIPLIER_NIGHT,
    PER_USER_BOOST,
    PER_USER_CAP,
    WINDOW_SECONDS,
    _DeviceBaseline,
    _diurnal_multiplier,
    _presence_multiplier,
)
from dataset.topology import load_topology
from schemas import (
    AccessResult,
    DeviceType,
    EventType,
    NetworkFlowPayload,
    UnifiedEvent,
)


FULL_TOPO_PATH = (
    Path(__file__).resolve().parents[1] / "topology" / "building_b1.yaml"
)
MINI_TOPO_PATH = (
    Path(__file__).resolve().parents[1] / "topology" / "building_b1_mini.yaml"
)
UTC = timezone.utc


# =============================================================================
# Full topology
# =============================================================================

class TestFullTopology:

    @pytest.fixture(scope="class")
    def topo(self):
        return load_topology(FULL_TOPO_PATH)

    def test_loads(self, topo):
        assert topo.building_id == "B1"
        assert len(topo.zones) == 8
        assert len(topo.users) == 50
        assert len(topo.doors) == 7

    def test_at_least_one_camera_per_zone(self, topo):
        cams = [d for d in topo.devices if d.type == DeviceType.CAMERA]
        zones_with_cam = {c.zone_id for c in cams}
        for z in topo.zones:
            assert z.zone_id in zones_with_cam, f"no camera in {z.zone_id}"

    def test_critical_zone_z8_exists(self, topo):
        z8 = topo.zone_index().get("Z8")
        assert z8 is not None
        assert z8.sensitivity.value == "CRITICAL"

    def test_only_few_users_can_access_z8(self, topo):
        """Sanity: with our config, only 4 IT users have Z8 in their typical_zones."""
        n = sum(1 for u in topo.users if "Z8" in u.typical_zones)
        # Allow small drift if the seed changes; just check it's tightly bounded.
        assert 1 <= n <= 8


# =============================================================================
# Network multipliers
# =============================================================================

class TestMultipliers:

    def test_diurnal_day(self):
        t = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        assert _diurnal_multiplier(t) == DIURNAL_MULTIPLIER_DAY

    def test_diurnal_night(self):
        t = datetime(2026, 4, 1, 3, 0, 0, tzinfo=UTC)
        assert _diurnal_multiplier(t) == DIURNAL_MULTIPLIER_NIGHT

    def test_diurnal_boundary_inclusive_start(self):
        """At DAY_START_HOUR exactly, we are in 'day'."""
        t = datetime(2026, 4, 1, DAY_START_HOUR, 0, 0, tzinfo=UTC)
        assert _diurnal_multiplier(t) == DIURNAL_MULTIPLIER_DAY

    def test_diurnal_boundary_exclusive_end(self):
        """At DAY_END_HOUR exactly, we are already 'night'."""
        t = datetime(2026, 4, 1, DAY_END_HOUR, 0, 0, tzinfo=UTC)
        assert _diurnal_multiplier(t) == DIURNAL_MULTIPLIER_NIGHT

    def test_presence_zero(self):
        assert _presence_multiplier(0) == 1.0

    def test_presence_capped(self):
        # With cap 3.0 and boost 0.4, anything over 5 users hits the cap.
        assert _presence_multiplier(100) == PER_USER_CAP

    def test_presence_monotonic(self):
        prev = _presence_multiplier(0)
        for n in range(1, 20):
            cur = _presence_multiplier(n)
            assert cur >= prev
            prev = cur


# =============================================================================
# Network flow content
# =============================================================================

class TestNetworkFlow:

    @pytest.fixture(scope="class")
    def topo(self):
        return load_topology(MINI_TOPO_PATH)

    @pytest.fixture(scope="class")
    def baselines(self, topo):
        return build_camera_baselines(topo, Rng(seed=42))

    def test_one_baseline_per_camera(self, topo, baselines):
        cams = [d for d in topo.devices if d.type == DeviceType.CAMERA]
        # The mini topology has no cameras; full has one per zone.
        # Just make sure the count matches.
        assert len(baselines) == len(cams)

    def test_camera_flow_event_validates(self, topo):
        topo_full = load_topology(FULL_TOPO_PATH)
        baselines = build_camera_baselines(topo_full, Rng(seed=42))
        first_baseline = next(iter(baselines.values()))
        # Find the zone_id for this baseline's device.
        zone_id = next(
            d.zone_id for d in topo_full.devices
            if d.device_id == first_baseline.device_id
        )
        ev = generate_camera_flow(
            topo=topo_full,
            baseline=first_baseline,
            zone_id=zone_id,
            timestamp=datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC),
            n_users_in_zone=2,
            rng=Rng(seed=99),
        )
        assert isinstance(ev, UnifiedEvent)
        assert ev.event_type == EventType.NETWORK_FLOW
        assert isinstance(ev.payload, NetworkFlowPayload)
        assert ev.payload.bytes_out >= 0
        assert ev.payload.bytes_in >= 0
        assert ev.payload.distinct_dst_ports >= 1
        assert ev.user_id is None  # network flows are unattributed

    def test_volumes_increase_with_presence(self):
        """
        Statistical test: average traffic over many samples should be
        clearly higher with users present than without.
        """
        topo_full = load_topology(FULL_TOPO_PATH)
        baselines = build_camera_baselines(topo_full, Rng(seed=42))
        baseline = next(iter(baselines.values()))
        zone_id = next(d.zone_id for d in topo_full.devices
                       if d.device_id == baseline.device_id)
        ts = datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC)

        empty_total = 0
        busy_total = 0
        for i in range(200):
            r1 = Rng(seed=i)
            r2 = Rng(seed=i + 10000)
            ev_empty = generate_camera_flow(
                topo=topo_full, baseline=baseline, zone_id=zone_id,
                timestamp=ts, n_users_in_zone=0, rng=r1,
            )
            ev_busy = generate_camera_flow(
                topo=topo_full, baseline=baseline, zone_id=zone_id,
                timestamp=ts, n_users_in_zone=5, rng=r2,
            )
            empty_total += ev_empty.payload.bytes_out
            busy_total += ev_busy.payload.bytes_out

        # 5 users gives 1 + 0.4*5 = 3.0 multiplier (capped). Should be
        # solidly above the empty average (with margin for randomness).
        assert busy_total > empty_total * 1.5, (
            f"empty avg={empty_total/200:.0f}, busy avg={busy_total/200:.0f} "
            "— presence multiplier seems broken"
        )


# =============================================================================
# Daily orchestrator
# =============================================================================

class TestGenerateDay:

    @pytest.fixture(scope="class")
    def topo(self):
        return load_topology(FULL_TOPO_PATH)

    def test_weekday_has_user_and_network_events(self, topo):
        wednesday = date(2026, 4, 1)  # check this is mid-week
        assert not is_weekend(wednesday)
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=wednesday, rng=rng)

        types = {e.event_type for e in events}
        # At least badge/door/motion AND network
        assert EventType.BADGE_ACCESS in types
        assert EventType.NETWORK_FLOW in types
        assert EventType.DOOR_OPENED in types
        assert EventType.MOTION_DETECTED in types

    def test_weekend_has_only_network_events(self, topo):
        saturday = date(2026, 4, 4)
        assert is_weekend(saturday)
        rng = Rng(seed=42)
        events = generate_day(topo=topo, day=saturday, rng=rng)

        # All events on a weekend must be NETWORK_FLOW (cameras still emit).
        for ev in events:
            assert ev.event_type == EventType.NETWORK_FLOW

        # Number of cameras × slots per day
        n_cameras = sum(1 for d in topo.devices if d.type == DeviceType.CAMERA)
        n_slots = int(86400 / WINDOW_SECONDS)
        assert len(events) == n_cameras * n_slots

    def test_events_globally_sorted(self, topo):
        wednesday = date(2026, 4, 1)
        events = generate_day(topo=topo, day=wednesday, rng=Rng(seed=42))
        ts = [e.timestamp for e in events]
        assert ts == sorted(ts)


# =============================================================================
# Multi-day baseline
# =============================================================================

class TestGenerateBaseline:

    @pytest.fixture(scope="class")
    def topo(self):
        return load_topology(FULL_TOPO_PATH)

    def test_short_baseline_runs(self, topo):
        """3-day generation completes and produces sensible counts."""
        events = list(generate_baseline(
            topo=topo,
            start_day=date(2026, 4, 1),  # Wed
            n_days=3,                    # Wed Thu Fri
            seed=42,
        ))
        # 3 weekdays × 50 users × ~5 badges + lots of network
        # Should be well over a few thousand.
        assert len(events) > 5000

        # Ordering across days must be respected.
        ts = [e.timestamp for e in events]
        # We don't enforce strict global sort across days because each day's
        # events are sorted internally; days are produced in order so the
        # sequence is non-decreasing.
        assert ts == sorted(ts), "events should be globally sorted"

    def test_baseline_deterministic(self, topo):
        """Same seed -> identical event count and timestamps."""
        a = list(generate_baseline(
            topo=topo, start_day=date(2026, 4, 1), n_days=2, seed=42,
        ))
        b = list(generate_baseline(
            topo=topo, start_day=date(2026, 4, 1), n_days=2, seed=42,
        ))
        assert len(a) == len(b)
        assert all(x.timestamp == y.timestamp for x, y in zip(a, b))
        assert all(x.event_type == y.event_type for x, y in zip(a, b))

    def test_no_user_events_outside_typical_zones(self, topo):
        """A user should never appear in a zone outside their typical_zones."""
        events = list(generate_baseline(
            topo=topo, start_day=date(2026, 4, 1), n_days=2, seed=42,
        ))
        user_idx = topo.user_index()
        for ev in events:
            if ev.user_id is None:
                continue
            user = user_idx[ev.user_id]
            assert ev.zone_id in user.typical_zones, (
                f"user {ev.user_id} in zone {ev.zone_id} but typical_zones="
                f"{user.typical_zones}"
            )
