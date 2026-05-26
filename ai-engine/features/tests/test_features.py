"""
Tests for step 3 — feature engineering.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from dataset.generators import Rng, generate_day, generate_user_day
from dataset.topology import load_topology
from features import (
    BaselineCatalog,
    FeatureExtractor,
    learn_baselines,
    read_events_jsonl,
    zscore,
)
from features.frequency import (
    WINDOW_5MIN,
    WINDOW_1H,
    FrequencyState,
)
from features.schema import COLUMN_NAMES, GROUPS, coerce_dataframe
from features.spatial import is_typical_zone_for_user, zone_sensitivity_lvl
from features.temporal import (
    hour_sin_cos,
    is_within_typical_hours,
    minutes_off_typical_midshift,
)
from schemas import (
    AccessResult,
    BadgeAccessPayload,
    EventType,
    NetworkFlowPayload,
    SeverityRaw,
    SourceLayer,
    UnifiedEvent,
    UserProfile,
    Zone,
    ZoneSensitivity,
)


UTC = timezone.utc
TOPO_PATH = (
    Path(__file__).resolve().parents[2] / "dataset" / "topology" / "building_b1.yaml"
)


@pytest.fixture(scope="module")
def topo():
    return load_topology(TOPO_PATH)


# =============================================================================
# Schema
# =============================================================================

class TestSchema:

    def test_column_groups_cover_all_columns(self):
        # Identity + temporal + spatial + frequency + network = ALL
        non_identity = (
            GROUPS.temporal + GROUPS.spatial + GROUPS.frequency + GROUPS.network
        )
        assert sorted(GROUPS.identity + non_identity) == sorted(COLUMN_NAMES)

    def test_numeric_for_if_excludes_identity(self):
        for c in GROUPS.numeric_for_if:
            assert c not in GROUPS.identity

    def test_coerce_rejects_missing_columns(self):
        df = pd.DataFrame({"event_id": ["a"]})
        with pytest.raises(KeyError, match="Missing"):
            coerce_dataframe(df)


# =============================================================================
# Temporal features (pure functions)
# =============================================================================

class TestTemporal:

    def _make_user(self, arrival="09:00:00", departure="18:00:00"):
        return UserProfile(
            user_id="u_test", name="Test", badge_id="b_test",
            typical_arrival=time.fromisoformat(arrival),
            typical_departure=time.fromisoformat(departure),
        )

    def _make_event(self, t: datetime, user_id="u_test"):
        return UnifiedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=t,
            building_id="B1", zone_id="Z2", device_id="R-Z2",
            user_id=user_id,
            payload=BadgeAccessPayload(
                badge_id="b_test",
                reader_device_id="R-Z2",
                access_result=AccessResult.GRANTED,
            ),
        )

    def test_hour_sin_cos_continuity_at_midnight(self):
        before = datetime(2026, 4, 1, 23, 59, 59, tzinfo=UTC)
        after = datetime(2026, 4, 2, 0, 0, 1, tzinfo=UTC)
        s1, c1 = hour_sin_cos(self._make_event(before))
        s2, c2 = hour_sin_cos(self._make_event(after))
        # The two values are 2s apart on a daily cycle; they should be very
        # close in (sin, cos) space.
        assert abs(s1 - s2) < 0.01
        assert abs(c1 - c2) < 0.01

    def test_within_typical_hours(self):
        user = self._make_user()
        in_hours = self._make_event(datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC))
        out_hours = self._make_event(datetime(2026, 4, 1, 3, 0, 0, tzinfo=UTC))
        assert is_within_typical_hours(in_hours, user) == 1
        assert is_within_typical_hours(out_hours, user) == 0

    def test_within_typical_hours_no_user(self):
        ev = self._make_event(datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC),
                              user_id=None)
        assert is_within_typical_hours(ev, None) == 0

    def test_minutes_off_midshift(self):
        user = self._make_user("09:00:00", "18:00:00")  # midpoint = 13:30
        ev = self._make_event(datetime(2026, 4, 1, 14, 30, 0, tzinfo=UTC))
        assert minutes_off_typical_midshift(ev, user) == 60.0
        ev_early = self._make_event(datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC))
        assert minutes_off_typical_midshift(ev_early, user) == -90.0

    def test_minutes_off_midshift_no_user(self):
        ev = self._make_event(datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
                              user_id=None)
        result = minutes_off_typical_midshift(ev, None)
        assert math.isnan(result)


# =============================================================================
# Spatial features
# =============================================================================

class TestSpatial:

    def test_zone_sensitivity_lvl(self):
        z_pub = Zone(zone_id="Z1", building_id="B1", name="Lobby",
                     sensitivity=ZoneSensitivity.PUBLIC)
        z_crit = Zone(zone_id="Z8", building_id="B1", name="Server",
                      sensitivity=ZoneSensitivity.CRITICAL)
        assert zone_sensitivity_lvl(z_pub) == 0
        assert zone_sensitivity_lvl(z_crit) == 3
        assert zone_sensitivity_lvl(None) == 1  # neutral fallback


# =============================================================================
# Frequency state (sliding windows)
# =============================================================================

class TestFrequencyState:

    def _ev(self, t: datetime, user_id: str = "u1", zone_id: str = "Z2",
            denied: bool = False):
        return UnifiedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=t, building_id="B1", zone_id=zone_id,
            device_id="R-Z2", user_id=user_id,
            payload=BadgeAccessPayload(
                badge_id="b1",
                reader_device_id="R-Z2",
                access_result=(
                    AccessResult.DENIED if denied else AccessResult.GRANTED
                ),
            ),
        )

    def test_user_count_5min_window(self):
        st = FrequencyState()
        t0 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        for i in range(3):
            st.observe(self._ev(t0 + timedelta(minutes=i)))
        # At t0 + 4min, 3 events should be in the 5-min window.
        n = st.events_for_user("u1", t0 + timedelta(minutes=4), WINDOW_5MIN)
        assert n == 3

    def test_pruning_drops_old_events(self):
        st = FrequencyState()
        # An event from 25h ago must be dropped after a fresh observe.
        old = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        new = datetime(2026, 4, 2, 1, 0, 0, tzinfo=UTC)
        st.observe(self._ev(old))
        st.observe(self._ev(new))
        # 24h window from `new` excludes `old` (25h apart).
        n = st.events_for_user(
            "u1", new, WINDOW_1H * 24
        )
        assert n == 1  # only the fresh event

    def test_denied_per_zone(self):
        st = FrequencyState()
        t0 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        for i in range(4):
            st.observe(self._ev(t0 + timedelta(seconds=10 * i),
                                user_id=None, denied=True))
        n = st.denied_for_zone("Z2", t0 + timedelta(seconds=40), WINDOW_5MIN)
        assert n == 4


# =============================================================================
# Baselines (learning + persistence)
# =============================================================================

class TestBaselines:

    def _net_event(self, device_id: str, bytes_out: int, bytes_in: int = 1000,
                   ports: int = 1):
        return UnifiedEvent(
            event_type=EventType.NETWORK_FLOW,
            source_layer=SourceLayer.CYBER,
            timestamp=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
            building_id="B1", zone_id="Z2", device_id=device_id,
            severity_raw=SeverityRaw.INFO,
            payload=NetworkFlowPayload(
                src_ip="10.0.10.1", dst_ip="10.0.20.1",
                bytes_out=bytes_out, bytes_in=bytes_in,
                distinct_dst_ports=ports, window_seconds=60.0,
            ),
        )

    def test_zscore_basic(self):
        assert zscore(10.0, 5.0, 5.0) == 1.0
        assert zscore(5.0, 5.0, 5.0) == 0.0
        assert zscore(0.0, 5.0, 5.0) == -1.0

    def test_zscore_zero_std(self):
        assert zscore(100.0, 5.0, 0.0) == 0.0

    def test_learn_constant_input_gives_zero_std_then_clamped(self):
        events = [self._net_event("CAM-1", 1000) for _ in range(50)]
        catalog = learn_baselines(events)
        b = catalog.per_device["CAM-1"]
        assert b.is_trusted()
        assert b.bytes_out_mean == 1000
        # Std clamped to >= 1.0 (per the implementation) so z-scores stay finite
        assert b.bytes_out_std >= 1.0

    def test_persistence_roundtrip(self, tmp_path):
        events = [self._net_event("CAM-1", 1000 + i * 10) for i in range(50)]
        original = learn_baselines(events)
        path = tmp_path / "baselines.json"
        original.write_json(path)
        loaded = BaselineCatalog.read_json(path)
        assert "CAM-1" in loaded.per_device
        assert loaded.per_device["CAM-1"].n_observations == 50
        assert abs(
            loaded.per_device["CAM-1"].bytes_out_mean
            - original.per_device["CAM-1"].bytes_out_mean
        ) < 1e-9

    def test_under_sampled_falls_back_to_global(self):
        # Only 5 events for CAM-1 (under threshold), so .get() returns global.
        events = [self._net_event("CAM-1", 1000)] * 5 + [
            self._net_event("CAM-2", 2000) for _ in range(50)
        ]
        catalog = learn_baselines(events)
        b = catalog.get("CAM-1")
        assert b.device_id == "__global__"
        b2 = catalog.get("CAM-2")
        assert b2.device_id == "CAM-2"


# =============================================================================
# Extractor end-to-end
# =============================================================================

class TestExtractor:

    @pytest.fixture(scope="class")
    def baselines(self, topo):
        # Learn baselines from one day of normal traffic (sufficient for tests).
        rng = Rng(seed=42)
        day_events = generate_day(topo=topo, day=date(2026, 4, 1), rng=rng)
        return learn_baselines(day_events)

    def test_extract_one_user_day(self, topo, baselines):
        user = topo.user_index()["u001"]
        rng = Rng(seed=42).derive("user", "u001")
        events = generate_user_day(
            profile=user, topo=topo, day=date(2026, 4, 1), rng=rng
        )
        extractor = FeatureExtractor(topology=topo, baselines=baselines)
        df = extractor.extract_dataframe(events)

        # One row per event, all canonical columns present, ordered.
        assert len(df) == len(events)
        assert list(df.columns) == COLUMN_NAMES

    def test_first_event_has_zero_history(self, topo, baselines):
        user = topo.user_index()["u001"]
        rng = Rng(seed=42).derive("user", "u001")
        events = generate_user_day(
            profile=user, topo=topo, day=date(2026, 4, 1), rng=rng
        )
        # extract just the first event
        extractor = FeatureExtractor(topology=topo, baselines=baselines)
        df = extractor.extract_dataframe(events[:1])
        # The very first event should not count itself in any window.
        assert df.iloc[0]["events_user_last_1h"] == 0
        assert df.iloc[0]["events_user_last_24h"] == 0

    def test_typical_zone_flag(self, topo, baselines):
        user = topo.user_index()["u001"]
        rng = Rng(seed=42).derive("user", "u001")
        events = generate_user_day(
            profile=user, topo=topo, day=date(2026, 4, 1), rng=rng
        )
        extractor = FeatureExtractor(topology=topo, baselines=baselines)
        df = extractor.extract_dataframe(events)
        # In the baseline, u001 only goes to her typical zones.
        attributed = df[df["user_id"] == "u001"]
        assert (attributed["is_typical_zone_for_user"] == 1).all()

    def test_network_features_zero_for_non_network(self, topo, baselines):
        user = topo.user_index()["u001"]
        rng = Rng(seed=42).derive("user", "u001")
        events = generate_user_day(
            profile=user, topo=topo, day=date(2026, 4, 1), rng=rng
        )
        extractor = FeatureExtractor(topology=topo, baselines=baselines)
        df = extractor.extract_dataframe(events)
        # All non-network rows must have NaN bytes_out and dst_is_external=0.
        non_net = df[df["event_type"] != "NETWORK_FLOW"]
        assert non_net["bytes_out"].isna().all()
        assert (non_net["dst_is_external"] == 0).all()

    def test_off_hours_event_has_low_typical_hours_flag(self, topo, baselines):
        """A 03:00 event should have is_within_typical_hours = 0."""
        from schemas import BadgeAccessPayload
        user = topo.user_index()["u001"]
        ev = UnifiedEvent(
            event_type=EventType.BADGE_ACCESS,
            source_layer=SourceLayer.PHYSICAL,
            timestamp=datetime(2026, 4, 1, 3, 0, 0, tzinfo=UTC),
            building_id="B1", zone_id="Z2", device_id="R-Z2",
            user_id=user.user_id,
            payload=BadgeAccessPayload(
                badge_id=user.badge_id, reader_device_id="R-Z2",
                access_result=AccessResult.GRANTED,
            ),
        )
        extractor = FeatureExtractor(topology=topo, baselines=baselines)
        df = extractor.extract_dataframe([ev])
        assert df.iloc[0]["is_within_typical_hours"] == 0