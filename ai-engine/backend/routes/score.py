"""GET /api/score/current — overall building threat snapshot."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..api_models import CurrentScoreOut, ZoneScoreOut

router = APIRouter(prefix="/api/score", tags=["score"])


def _classify(score: float) -> str:
    """Reuse the README mapping: NORMAL/SUSPECT/CRITICAL."""
    if score >= 0.7:
        return "CRITICAL"
    if score >= 0.3:
        return "SUSPECT"
    return "NORMAL"


@router.get("/current", response_model=CurrentScoreOut)
def get_current_score(request: Request) -> CurrentScoreOut:
    store = request.app.state.store
    topo = store.topology()
    zone_scores = store.current_zone_scores()

    zones_out: list[ZoneScoreOut] = []
    for z in topo.zones:
        score = zone_scores.get(z.zone_id, 0.0)
        zones_out.append(ZoneScoreOut(
            zone_id=z.zone_id,
            zone_name=z.name,
            sensitivity=z.sensitivity.value,
            current_score=score,
            classification=_classify(score),
        ))

    n_active = len(store.active_alerts())
    return CurrentScoreOut(
        timestamp=datetime.now(timezone.utc),
        building_id=topo.building_id,
        zones=zones_out,
        n_active_alerts=n_active,
    )