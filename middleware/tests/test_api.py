import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.event import Event
from app.services.ai_engine_client import to_unified_event


@pytest.mark.anyio
async def test_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "running" in response.json()["message"]


@pytest.mark.anyio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_create_and_list_events():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        event_data = {
            "event_id": "evt-001",
            "event_type": "badge_access",
            "source_device": "badge-reader-01",
            "location": "zone-A",
            "details": {"badge_id": "B-1234", "access": "granted"},
        }
        response = await client.post("/api/events", json=event_data)
        assert response.status_code == 200
        assert response.json()["event_id"] == "evt-001"

        response = await client.get("/api/events")
        assert response.status_code == 200
        assert len(response.json()) >= 1


def test_event_is_normalized_for_ai_engine():
    event = Event(
        event_id="evt-bridge-001",
        event_type="door_sensor",
        source_device="D-Z8-01",
        location="Z8",
        details={"state": "forced", "door_id": "D-Z2-Z8"},
    )

    payload = to_unified_event(event)

    assert payload["event_type"] == "DOOR_FORCED"
    assert payload["source_layer"] == "PHYSICAL"
    assert payload["zone_id"] == "Z8"
    assert payload["payload"]["kind"] == "DOOR_FORCED"
    assert payload["payload"]["no_badge_window_seconds"] == 10.0
