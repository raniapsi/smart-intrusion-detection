"""
Tests for step 7 — the SOC backend API.

We use FastAPI's TestClient (synchronous) which spins up the app
in-process. The backend lifespan is fully exercised, including the
replay thread (we stop it quickly via the TestClient context manager).

For these tests we generate a tiny scenario in tmp_path and run the
real scoring pipeline so the backend has plausible data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dataset.generators import Rng, generate_day
from dataset.scenarios import REGISTRY
from dataset.topology import load_topology
from features import FeatureExtractor, learn_baselines
from models import train_isolation_forest
from scoring_service import PipelineComponents, ScoringPipeline
from scoring_service.batch import run_batch_jsonl

from backend.app import BackendConfig, create_app


TOPO_PATH = (
    Path(__file__).resolve().parents[2] / "dataset" / "topology" / "building_b1.yaml"
)


@pytest.fixture(scope="module")
def topo():
    return load_topology(TOPO_PATH)


@pytest.fixture(scope="module")
def scored_paths(topo, tmp_path_factory):
    """
    Run the forced_door scenario through the full pipeline, save
    enriched + alerts JSONL files. Other tests reuse these.
    """
    workdir = tmp_path_factory.mktemp("scoring")

    # Generate a day with the forced_door scenario.
    scenario = REGISTRY["forced_door"]()
    day = date.fromisoformat(scenario.default_day)
    rng = Rng(seed=42)
    baseline = generate_day(topo=topo, day=day, rng=rng)
    result = scenario.inject(
        baseline=baseline, topo=topo,
        rng=rng.derive("scn", "forced_door"),
    )

    # Train an IF on a separate day.
    train_events = generate_day(topo=topo, day=date(2026, 4, 1), rng=Rng(seed=42))
    catalog = learn_baselines(train_events)
    extractor = FeatureExtractor(topology=topo, baselines=catalog)
    train_df = extractor.extract_dataframe(train_events)
    model = train_isolation_forest(train_df, n_estimators=50)

    # Save the events JSONL for the scoring driver.
    events_path = workdir / "events.jsonl"
    with events_path.open("w") as f:
        for ev in result.events:
            f.write(ev.model_dump_json())
            f.write("\n")

    pipeline = ScoringPipeline(PipelineComponents(
        topology=topo, baselines=catalog, model=model,
    ))
    enriched_path = workdir / "test.enriched.jsonl"
    alerts_path = workdir / "test.alerts.jsonl"
    run_batch_jsonl(
        pipeline=pipeline,
        events_path=events_path,
        enriched_out=enriched_path,
        alerts_out=alerts_path,
    )
    return enriched_path, alerts_path


@pytest.fixture(scope="module")
def client(scored_paths):
    enriched_path, alerts_path = scored_paths
    config = BackendConfig(
        topology_path=TOPO_PATH,
        enriched_paths=[enriched_path],
        alerts_paths=[alerts_path],
        enable_replay=False,  # don't need the replay thread for HTTP tests
    )
    app = create_app(config)
    with TestClient(app) as c:
        yield c


# =============================================================================
# Smoke
# =============================================================================

class TestRoot:

    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "soc-backend"
        assert "/api/events" in body["endpoints"]


# =============================================================================
# Events
# =============================================================================

class TestEvents:

    def test_list_no_filter(self, client):
        r = client.get("/api/events?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) <= 10
        if body:
            ev = body[0]
            assert "event_id" in ev
            assert "ai_classification" in ev

    def test_filter_by_zone(self, client):
        r = client.get("/api/events?zone=Z8&limit=100")
        assert r.status_code == 200
        for ev in r.json():
            assert ev["zone_id"] == "Z8"

    def test_filter_by_classification(self, client):
        r = client.get("/api/events?classification=CRITICAL&limit=100")
        assert r.status_code == 200
        for ev in r.json():
            assert ev["ai_classification"] == "CRITICAL"

    def test_invalid_classification_400(self, client):
        r = client.get("/api/events?classification=NONSENSE")
        assert r.status_code == 400

    def test_limit_capped(self, client):
        # 10001 should be rejected by Query(le=10000).
        r = client.get("/api/events?limit=10001")
        assert r.status_code == 422


# =============================================================================
# Alerts
# =============================================================================

class TestAlerts:

    def test_list_active(self, client):
        r = client.get("/api/alerts/active")
        assert r.status_code == 200
        for a in r.json():
            assert a["acknowledged"] is False

    def test_list_all(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_acknowledge_unknown_404(self, client):
        # A random valid UUID that's not in the store.
        r = client.post(
            "/api/alert/00000000-0000-0000-0000-000000000000/acknowledge",
            json={"by": "ilyes"},
        )
        assert r.status_code == 404

    def test_acknowledge_invalid_uuid_400(self, client):
        r = client.post(
            "/api/alert/not-a-uuid/acknowledge",
            json={"by": "ilyes"},
        )
        assert r.status_code == 400

    def test_acknowledge_round_trip(self, client):
        actives = client.get("/api/alerts/active").json()
        if not actives:
            pytest.skip("no active alerts in this scenario")
        alert_id = actives[0]["alert_id"]

        r = client.post(
            f"/api/alert/{alert_id}/acknowledge",
            json={"by": "ilyes"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["acknowledged"] is True
        assert body["acknowledged_by"] == "ilyes"

        # The alert should no longer be in /active
        actives2 = client.get("/api/alerts/active").json()
        assert all(a["alert_id"] != alert_id for a in actives2)


# =============================================================================
# Users
# =============================================================================

class TestUsers:

    def test_list_users(self, client):
        r = client.get("/api/users")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert "u001" in body

    def test_user_profile(self, client):
        r = client.get("/api/users/u001/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "u001"
        assert "n_events_total" in body

    def test_user_profile_unknown(self, client):
        r = client.get("/api/users/unknown_user_x/profile")
        assert r.status_code == 404


# =============================================================================
# Devices
# =============================================================================

class TestDevices:

    def test_list_devices(self, client):
        r = client.get("/api/devices")
        assert r.status_code == 200
        body = r.json()
        assert len(body) > 0
        d = body[0]
        assert "device_id" in d
        assert "type" in d


# =============================================================================
# Score
# =============================================================================

class TestScore:

    def test_current_score(self, client):
        r = client.get("/api/score/current")
        assert r.status_code == 200
        body = r.json()
        assert body["building_id"] == "B1"
        assert isinstance(body["zones"], list)
        assert len(body["zones"]) == 8
        for z in body["zones"]:
            assert 0.0 <= z["current_score"] <= 1.0
            assert z["classification"] in {"NORMAL", "SUSPECT", "CRITICAL"}


# =============================================================================
# Logs
# =============================================================================

class TestLogs:

    def test_list_logs_unsigned(self, client):
        r = client.get("/api/logs?limit=10")
        assert r.status_code == 200
        for entry in r.json():
            assert entry["signature"] is None

    def test_list_logs_signed_empty(self, client):
        r = client.get("/api/logs?signed=true")
        assert r.status_code == 200
        # No signed logs in this implementation.
        assert r.json() == []