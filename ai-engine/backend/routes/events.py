"""GET /api/events — filtered query."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from schemas import AIClassification

from ..api_models import EventOut

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(
    request: Request,
    zone: Optional[str] = Query(None, description="Filter by zone_id"),
    user_id: Optional[str] = Query(None, description="Filter by user_id"),
    classification: Optional[str] = Query(
        None, description="NORMAL | SUSPECT | CRITICAL",
    ),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=10000),
) -> list[EventOut]:
    store = request.app.state.store

    cls_enum: Optional[AIClassification] = None
    if classification is not None:
        try:
            cls_enum = AIClassification(classification.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"invalid classification '{classification}'",
            )

    events = store.query_events(
        zone=zone, user_id=user_id, from_ts=from_ts, to_ts=to_ts,
        classification=cls_enum, limit=limit,
    )
    return [
        EventOut(
            event_id=str(ev.event_id),
            timestamp=ev.timestamp,
            event_type=ev.event_type.value,
            source_layer=ev.source_layer.value,
            zone_id=ev.zone_id,
            device_id=ev.device_id,
            user_id=ev.user_id,
            ai_score=ev.ai_score,
            ai_classification=ev.ai_classification.value,
        )
        for ev in events
    ]