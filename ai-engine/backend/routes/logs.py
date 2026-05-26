"""
GET /api/logs — auditable log export.

In a real deployment, the logs are signed by the security team's PQC
log signer (README section 4.3, ECC-hybrid-MLDSA5). For now we expose
the unsigned events with a `signature: null` placeholder. When the
signer lands, the route will be upgraded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request

from ..api_models import LogOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogOut])
def list_logs(
    request: Request,
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    signed: bool = Query(False, description="Filter to signed logs only (always empty for now)"),
    limit: int = Query(1000, ge=1, le=50000),
) -> list[LogOut]:
    store = request.app.state.store

    if signed:
        # No signed logs available yet — see route docstring.
        return []

    events = store.query_events(from_ts=from_ts, to_ts=to_ts, limit=limit)
    return [
        LogOut(
            event_id=str(ev.event_id),
            timestamp=ev.timestamp,
            event_type=ev.event_type.value,
            zone_id=ev.zone_id,
            user_id=ev.user_id,
            ai_score=ev.ai_score,
            ai_classification=ev.ai_classification.value,
            signature=None,
        )
        for ev in events
    ]