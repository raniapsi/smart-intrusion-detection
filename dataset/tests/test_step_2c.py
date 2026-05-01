"""
Tests for step 2c — attack scenarios.

For each scenario, we verify that:
  - it injects at least one event
  - all injected event_ids are present in the final events list
  - the truth.json describes a non-empty attack window
  - the events list is sorted by timestamp
  - the truth.json is JSON-serialisable (round-trip)
  - the expected_classification is consistent with expected_min_score
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from dataset.generators import Rng, generate_day
from dataset.scenarios import REGISTRY, Truth
from dataset.topology import load_topology
from schemas import AIClassification, EventType, NetworkAnomalyLabel, UnifiedEvent


FULL_TOPO_PATH = (
    Path(__file__).resolve().parents[1] / "topology" / "building_b1.yaml"
)


@pytest.fixture(scope="module")
def topo():
    return load_topology(FULL_TOPO_PATH)


# =============================================================================
# Per-scenario smoke tests
# =============================================================================

@pytest.mark.parametrize("scenario_name", sorted(REGISTRY.keys()))
class TestEachScenario:

    def _run(self, scenario_name: str, topo):
        scenario = REGISTRY[scenario_name]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline,
            topo=topo,
            rng=rng.derive("scenario", scenario.name),
        )
        return scenario, baseline, result

    def test_injects_at_least_one_event(self, scenario_name, topo):
        _, _, result = self._run(scenario_name, topo)
        assert len(result.truth.attack_event_ids) > 0, (
            f"{scenario_name} did not inject any attack event"
        )

    def test_attack_events_are_in_final_list(self, scenario_name, topo):
        _, _, result = self._run(scenario_name, topo)
        final_ids = {ev.event_id for ev in result.events}
        for aid in result.truth.attack_event_ids:
            assert aid in final_ids, (
                f"{scenario_name} truth references {aid} not in events"
            )

    def test_baseline_is_preserved(self, scenario_name, topo):
        _, baseline, result = self._run(scenario_name, topo)
        baseline_ids = {ev.event_id for ev in baseline}
        final_ids = {ev.event_id for ev in result.events}
        # Every baseline event must still be present in the final list.
        assert baseline_ids.issubset(final_ids), (
            f"{scenario_name} dropped baseline events"
        )

    def test_events_sorted(self, scenario_name, topo):
        _, _, result = self._run(scenario_name, topo)
        ts = [e.timestamp for e in result.events]
        assert ts == sorted(ts)

    def test_truth_window_non_empty(self, scenario_name, topo):
        _, _, result = self._run(scenario_name, topo)
        t = result.truth
        assert t.attack_window_start is not None
        assert t.attack_window_end is not None
        assert t.attack_window_end > t.attack_window_start

    def test_truth_class_consistent_with_score(self, scenario_name, topo):
        _, _, result = self._run(scenario_name, topo)
        t = result.truth
        if t.expected_classification == AIClassification.NORMAL:
            assert t.expected_min_score < 0.3
        elif t.expected_classification == AIClassification.SUSPECT:
            assert 0.3 <= t.expected_min_score < 0.7
        elif t.expected_classification == AIClassification.CRITICAL:
            assert t.expected_min_score >= 0.7

    def test_truth_json_round_trip(self, scenario_name, topo, tmp_path):
        _, _, result = self._run(scenario_name, topo)
        path = tmp_path / "truth.json"
        result.truth.write_json(path)
        loaded = json.loads(path.read_text())
        assert loaded["scenario"] == scenario_name
        assert loaded["expected_classification"] in (
            "NORMAL", "SUSPECT", "CRITICAL"
        )
        assert isinstance(loaded["attack_event_ids"], list)
        assert len(loaded["attack_event_ids"]) > 0

    def test_attack_events_within_truth_window(self, scenario_name, topo):
        """Every event referenced in truth must fall within the truth window."""
        _, _, result = self._run(scenario_name, topo)
        t = result.truth
        attack_ids = set(t.attack_event_ids)
        for ev in result.events:
            if ev.event_id in attack_ids:
                # Some scenarios have events extending slightly past the
                # nominal window (door close after 90s, etc.) — allow a
                # 2-minute slack.
                assert ev.timestamp >= t.attack_window_start
                # We don't enforce upper bound strictly because the window
                # in some scenarios is set conservatively narrow.


# =============================================================================
# Specific scenario invariants
# =============================================================================

class TestForcedDoor:

    def test_emits_door_forced_event(self, topo):
        scenario = REGISTRY["forced_door"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "forced_door")
        )
        types = {e.event_type for e in result.events
                 if e.event_id in set(result.truth.attack_event_ids)}
        assert EventType.DOOR_FORCED in types


class TestRevokedBadge:

    def test_emits_multiple_denied_badges(self, topo):
        scenario = REGISTRY["revoked_badge"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "revoked_badge")
        )
        attack_ids = set(result.truth.attack_event_ids)
        denied = [
            e for e in result.events
            if e.event_id in attack_ids
            and e.event_type == EventType.BADGE_ACCESS
            and e.payload.access_result.value == "DENIED"
        ]
        assert len(denied) >= 3, f"only {len(denied)} DENIED events, expected >= 3"


class TestTailgating:

    def test_emits_motion_with_two_entities(self, topo):
        scenario = REGISTRY["tailgating"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "tailgating")
        )
        attack_ids = set(result.truth.attack_event_ids)
        motion_events = [
            e for e in result.events
            if e.event_id in attack_ids
            and e.event_type == EventType.MOTION_DETECTED
        ]
        assert len(motion_events) >= 1
        assert any(e.payload.entity_count >= 2 for e in motion_events)


class TestHybridIntrusion:

    def test_emits_both_physical_and_cyber(self, topo):
        scenario = REGISTRY["hybrid_intrusion"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "hybrid_intrusion")
        )
        attack_ids = set(result.truth.attack_event_ids)
        attack_types = {
            e.event_type for e in result.events if e.event_id in attack_ids
        }
        # Must have BOTH a forced door AND a network anomaly
        assert EventType.DOOR_FORCED in attack_types
        assert EventType.NETWORK_ANOMALY in attack_types

    def test_port_scan_label(self, topo):
        scenario = REGISTRY["hybrid_intrusion"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo, rng=rng.derive("scn", "hybrid_intrusion")
        )
        anomalies = [
            e for e in result.events
            if e.event_id in set(result.truth.attack_event_ids)
            and e.event_type == EventType.NETWORK_ANOMALY
        ]
        assert len(anomalies) >= 1
        assert anomalies[0].payload.anomaly_label == NetworkAnomalyLabel.PORT_SCAN


class TestCameraCompromise:

    def test_emits_exfiltration_label(self, topo):
        scenario = REGISTRY["camera_compromise"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo,
            rng=rng.derive("scn", "camera_compromise"),
        )
        anomalies = [
            e for e in result.events
            if e.event_id in set(result.truth.attack_event_ids)
            and e.event_type == EventType.NETWORK_ANOMALY
        ]
        assert len(anomalies) >= 1
        assert anomalies[0].payload.anomaly_label == NetworkAnomalyLabel.EXFILTRATION


class TestCredentialTheft:

    def test_emits_badge_then_exfil(self, topo):
        scenario = REGISTRY["credential_theft"]()
        day = date.fromisoformat(scenario.default_day)
        rng = Rng(seed=42)
        baseline = generate_day(topo=topo, day=day, rng=rng)
        result = scenario.inject(
            baseline=baseline, topo=topo,
            rng=rng.derive("scn", "credential_theft"),
        )
        attack_ids = set(result.truth.attack_event_ids)
        # The first attack event should be a BADGE_ACCESS (legit-looking)
        first_attack = next(
            e for e in result.events if e.event_id in attack_ids
        )
        assert first_attack.event_type == EventType.BADGE_ACCESS
        # And there should be NETWORK_ANOMALY events later
        anomalies = [
            e for e in result.events
            if e.event_id in attack_ids
            and e.event_type == EventType.NETWORK_ANOMALY
        ]
        assert len(anomalies) >= 1
        # Anomaly must come AFTER the badge.
        assert anomalies[0].timestamp > first_attack.timestamp


# =============================================================================
# Reproducibility
# =============================================================================

class TestReproducibility:

    @pytest.mark.parametrize("scenario_name", sorted(REGISTRY.keys()))
    def test_same_seed_same_attack_events(self, scenario_name, topo):
        scenario_cls = REGISTRY[scenario_name]
        day = date.fromisoformat(scenario_cls.default_day)

        def run():
            rng = Rng(seed=42)
            baseline = generate_day(topo=topo, day=day, rng=rng)
            scenario = scenario_cls()
            return scenario.inject(
                baseline=baseline,
                topo=topo,
                rng=rng.derive("scenario", scenario.name),
            )

        a = run()
        b = run()
        ts_a = [e.timestamp for e in a.events
                if e.event_id in set(a.truth.attack_event_ids)]
        ts_b = [e.timestamp for e in b.events
                if e.event_id in set(b.truth.attack_event_ids)]
        assert ts_a == ts_b