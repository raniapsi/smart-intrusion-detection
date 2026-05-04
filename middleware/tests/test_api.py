import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


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
