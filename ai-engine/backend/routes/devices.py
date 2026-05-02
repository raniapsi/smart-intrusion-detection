"""GET /api/devices — device inventory."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..api_models import DeviceOut

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
def list_devices(request: Request) -> list[DeviceOut]:
    store = request.app.state.store
    return [
        DeviceOut(
            device_id=d.device_id,
            type=d.type.value,
            zone_id=d.zone_id,
            ip_address=d.ip_address,
        )
        for d in store.all_devices()
    ]