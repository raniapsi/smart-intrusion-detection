"""POST /api/ingest/events — live middleware ingestion."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from schemas import Alert, EnrichedEvent, UnifiedEvent

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enriched_event: EnrichedEvent
    alert: Optional[Alert] = None


@router.post(
    "/events",
    response_model=IngestEventOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_event(request: Request, event: UnifiedEvent) -> IngestEventOut:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "live scoring is not configured; start backend with "
                "--baselines and --model"
            ),
        )

    enriched, alert = pipeline.process_event(event)
    store = request.app.state.store
    store.add_event(enriched)
    if alert is not None:
        store.add_alert(alert)

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is not None and enriched.ai_classification.value != "NORMAL":
        await ws_manager.broadcast({
            "type": "event",
            "event_id": str(enriched.event_id),
            "timestamp": enriched.timestamp.isoformat(),
            "event_type": enriched.event_type.value,
            "zone_id": enriched.zone_id,
            "device_id": enriched.device_id,
            "user_id": enriched.user_id,
            "ai_score": enriched.ai_score,
            "ai_classification": enriched.ai_classification.value,
        })

    return IngestEventOut(enriched_event=enriched, alert=alert)
