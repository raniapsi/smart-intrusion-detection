"""GET /api/users/{user_id}/profile — user history & stats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from schemas import AIClassification

from ..api_models import UserProfileOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[str])
def list_users(request: Request) -> list[str]:
    store = request.app.state.store
    return [u.user_id for u in store.all_users()]


@router.get("/{user_id}/profile", response_model=UserProfileOut)
def get_user_profile(user_id: str, request: Request) -> UserProfileOut:
    store = request.app.state.store
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    events = store.query_events(user_id=user_id)
    n_critical = sum(
        1 for e in events if e.ai_classification == AIClassification.CRITICAL
    )
    n_suspect = sum(
        1 for e in events if e.ai_classification == AIClassification.SUSPECT
    )
    last_seen = max((e.timestamp for e in events), default=None)

    return UserProfileOut(
        user_id=user.user_id,
        name=user.name,
        badge_id=user.badge_id,
        typical_zones=list(user.typical_zones),
        typical_arrival=user.typical_arrival.isoformat(),
        typical_departure=user.typical_departure.isoformat(),
        n_events_total=len(events),
        n_critical_events=n_critical,
        n_suspect_events=n_suspect,
        last_seen=last_seen,
    )