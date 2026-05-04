from fastapi import APIRouter
from app.models.event import Event
from app.models.alert import Alert, AlertLevel

router = APIRouter()

# In-memory storage for MVP
events_store: list[Event] = []
alerts_store: list[Alert] = []


@router.post("/events", response_model=Event)
async def create_event(event: Event):
    """Receive and store a new IoT or cyber event."""
    events_store.append(event)
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
