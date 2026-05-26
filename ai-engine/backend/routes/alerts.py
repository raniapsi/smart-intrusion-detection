"""
Alerts routes:
  GET  /api/alerts/active        — non-acknowledged alerts
  POST /api/alert/{id}/acknowledge — mark as acknowledged
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ..api_models import AcknowledgeIn, AcknowledgeOut, AlertOut

router = APIRouter(tags=["alerts"])


def _alert_to_out(al) -> AlertOut:
    return AlertOut(
        alert_id=str(al.alert_id),
        created_at=al.created_at,
        triggering_event_id=str(al.triggering_event_id),
        building_id=al.building_id,
        zone_id=al.zone_id,
        user_id=al.user_id,
        classification=al.classification.value,
        score=al.score,
        title=al.title,
        description=al.description,
        contributing_detectors=list(al.contributing_detectors),
        suggested_action=al.suggested_action,
        acknowledged=al.acknowledged,
        acknowledged_by=al.acknowledged_by,
        acknowledged_at=al.acknowledged_at,
    )


@router.get("/api/alerts/active", response_model=list[AlertOut])
def list_active_alerts(request: Request) -> list[AlertOut]:
    store = request.app.state.store
    return [_alert_to_out(a) for a in store.active_alerts()]


@router.get("/api/alerts", response_model=list[AlertOut])
def list_all_alerts(request: Request) -> list[AlertOut]:
    """All alerts (acknowledged or not). Useful for the Logs tab."""
    store = request.app.state.store
    return [_alert_to_out(a) for a in store.all_alerts()]


@router.post(
    "/api/alert/{alert_id}/acknowledge",
    response_model=AcknowledgeOut,
)
def acknowledge_alert(
    alert_id: str, body: AcknowledgeIn, request: Request,
) -> AcknowledgeOut:
    try:
        uid = UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid alert_id")

    store = request.app.state.store
    now = datetime.now(timezone.utc)
    alert = store.acknowledge_alert(uid, body.by, now)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")

    return AcknowledgeOut(
        alert_id=str(alert.alert_id),
        acknowledged=True,
        acknowledged_by=alert.acknowledged_by or "",
        acknowledged_at=alert.acknowledged_at or now,
    )