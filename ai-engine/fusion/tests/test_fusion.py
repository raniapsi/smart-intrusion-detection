"""
Tests for the fusion package — correlator and scorer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from fusion import correlate_physical_cyber, fuse_scores


UTC = timezone.utc


def _df(rows: list[dict]) -> pd.DataFrame:
    """Helper: build a DataFrame from a list of dicts, with proper dtypes."""
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


# =============================================================================
# Correlator
# =============================================================================

class TestCorrelator:

    def test_no_correlation_when_alone(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
        ])
        peer = correlate_physical_cyber(df, score_column="score_x")
        assert (peer == 0.0).all()

    def test_simple_correlation_inside_window(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.8},
        ])
        peer = correlate_physical_cyber(df, score_column="score_x", window_seconds=60.0)
        # Each event correlates with the other (opposite layer, same zone, in window).
        assert peer.iloc[0] == pytest.approx(0.8)
        assert peer.iloc[1] == pytest.approx(0.9)

    def test_no_correlation_across_zones(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z2", "score_x": 0.8},
        ])
        peer = correlate_physical_cyber(df, score_column="score_x", window_seconds=60.0)
        assert (peer == 0.0).all()

    def test_no_correlation_outside_window(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
            {"timestamp": datetime(2026, 4, 1, 12, 5, 0, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.8},
        ])
        peer = correlate_physical_cyber(df, score_column="score_x", window_seconds=60.0)
        # 5 minutes apart, way outside 60s window.
        assert (peer == 0.0).all()

    def test_no_correlation_below_min_peer(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.10},
        ])
        peer = correlate_physical_cyber(
            df, score_column="score_x", min_peer_score=0.30,
        )
        # Cyber peer is below threshold so PHYSICAL gets no correlation.
        assert peer.iloc[0] == 0.0
        # And the cyber event sees the physical at 0.9 (above threshold).
        assert peer.iloc[1] == pytest.approx(0.9)

    def test_multiple_peers_takes_max(self):
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.5},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 10, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.4},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 20, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.85},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.6},
        ])
        peer = correlate_physical_cyber(df, score_column="score_x", window_seconds=60.0)
        # PHYSICAL row should see the strongest cyber peer (0.85).
        assert peer.iloc[0] == pytest.approx(0.85)

    def test_index_preserved(self):
        """The output Series must align with df.index, not the sort order."""
        df = _df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),  # later
             "source_layer": "PHYSICAL", "zone_id": "Z1", "score_x": 0.9},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),   # earlier
             "source_layer": "CYBER", "zone_id": "Z1", "score_x": 0.8},
        ])
        # df is in REVERSE chronological order. The correlator must return
        # peer scores in df's order (not in sorted order).
        peer = correlate_physical_cyber(df, score_column="score_x")
        # df.iloc[0] is PHYSICAL → peer should be 0.8 (the cyber)
        assert peer.iloc[0] == pytest.approx(0.8)
        # df.iloc[1] is CYBER → peer should be 0.9 (the physical)
        assert peer.iloc[1] == pytest.approx(0.9)


# =============================================================================
# Scorer
# =============================================================================

class TestFusionScorer:

    def _df(self, rows):
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    def test_basic_max(self):
        """Without correlation, score_final equals max(rules, if)."""
        df = self._df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.85, "score_if": 0.30},
        ])
        out = fuse_scores(df)
        assert out.iloc[0]["score_combined"] == pytest.approx(0.85)
        assert out.iloc[0]["score_correlation_peer"] == 0.0
        assert out.iloc[0]["score_final"] == pytest.approx(0.85)
        assert out.iloc[0]["ai_classification"] == "CRITICAL"

    def test_correlation_bonus_proportional_to_margin(self):
        """
        Two correlated events with a base of 0.50 each should be lifted
        toward 0.65 by a correlation bonus of 0.30 × 0.50 × (1 - 0.50) = 0.075.
        Wait — the bonus formula is 0.30 × peer × (1 - combined).
        peer = 0.50 (the other side's combined), combined = 0.50.
        bonus = 0.30 × 0.50 × (1 - 0.50) = 0.075 → final = 0.575.
        """
        df = self._df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.50, "score_if": 0.0},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 30, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1",
             "score_rules": 0.0, "score_if": 0.50},
        ])
        out = fuse_scores(df, correlation_weight=0.30)
        # Both events have combined=0.50 and peer=0.50.
        # bonus = 0.30 × 0.50 × 0.50 = 0.075 → final = 0.575
        for i in (0, 1):
            assert out.iloc[i]["score_correlation_peer"] == pytest.approx(0.50)
            assert out.iloc[i]["score_final"] == pytest.approx(0.575, abs=1e-3)
            assert out.iloc[i]["ai_classification"] == "SUSPECT"

    def test_correlation_lifts_suspect_to_critical(self):
        """A 0.65 + strong correlation peer should reach CRITICAL (>= 0.7)."""
        df = self._df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.65, "score_if": 0.0},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 5, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1",
             "score_rules": 0.85, "score_if": 0.0},
        ])
        out = fuse_scores(df, correlation_weight=0.30)
        # PHYSICAL (combined 0.65, peer 0.85): bonus = 0.30 × 0.85 × 0.35 = 0.0893
        # final = 0.7393 → CRITICAL
        phys = out[out["score_combined"] == 0.65].iloc[0]
        assert phys["score_final"] >= 0.70
        assert phys["ai_classification"] == "CRITICAL"

    def test_high_score_gets_small_bonus(self):
        """An event already at 0.95 only gets a tiny bonus (low margin)."""
        df = self._df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.95, "score_if": 0.0},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 5, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1",
             "score_rules": 0.85, "score_if": 0.0},
        ])
        out = fuse_scores(df, correlation_weight=0.30)
        phys = out.iloc[0]
        # margin = 1 - 0.95 = 0.05; bonus = 0.30 × 0.85 × 0.05 = 0.01275
        # final = 0.96275
        assert phys["score_final"] == pytest.approx(0.96275, abs=1e-3)

    def test_score_clipped_to_one(self):
        """score_final is bounded by 1.0 even with extreme inputs."""
        # We can't easily construct combined=1 + bonus > 0 because
        # margin = 1 - 1 = 0. But we can test the clip path with a large
        # correlation weight as a regression check.
        df = self._df([
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.5, "score_if": 0.5},
            {"timestamp": datetime(2026, 4, 1, 12, 0, 5, tzinfo=UTC),
             "source_layer": "CYBER", "zone_id": "Z1",
             "score_rules": 1.0, "score_if": 1.0},
        ])
        # Even if we crank weight super high, score_final must stay <= 1.
        out = fuse_scores(df, correlation_weight=10.0)
        assert (out["score_final"] <= 1.0).all()

    def test_classification_thresholds(self):
        """Verify the NORMAL/SUSPECT/CRITICAL mapping."""
        df = self._df([
            # NORMAL
            {"timestamp": datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z1",
             "score_rules": 0.0, "score_if": 0.1},
            # SUSPECT
            {"timestamp": datetime(2026, 4, 1, 12, 1, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z2",
             "score_rules": 0.0, "score_if": 0.5},
            # CRITICAL
            {"timestamp": datetime(2026, 4, 1, 12, 2, 0, tzinfo=UTC),
             "source_layer": "PHYSICAL", "zone_id": "Z3",
             "score_rules": 0.0, "score_if": 0.85},
        ])
        out = fuse_scores(df)
        assert out.iloc[0]["ai_classification"] == "NORMAL"
        assert out.iloc[1]["ai_classification"] == "SUSPECT"
        assert out.iloc[2]["ai_classification"] == "CRITICAL"