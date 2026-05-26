import logging

from fastapi import APIRouter, BackgroundTasks
from app.models.event import Event
from app.models.alert import Alert, AlertLevel
from app.services.ai_engine_client import forward_event_to_ai

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory storage for MVP
events_store: list[Event] = []
alerts_store: list[Alert] = []


async def _forward_event(event: Event) -> None:
    try:
        await forward_event_to_ai(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to forward event %s to AI engine: %s", event.event_id, exc)


@router.post("/events", response_model=Event)
async def create_event(event: Event, background_tasks: BackgroundTasks):
    """Receive and store a new IoT or cyber event."""
    events_store.append(event)
    background_tasks.add_task(_forward_event, event)
    return event


@router.get("/events", response_model=list[Event])
async def list_events():
    """List all received events."""
    return events_store


@router.get("/alerts", response_model=list[Alert])
async def list_alerts():
    """List all generated alerts."""
    return alerts_store


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
