from __future__ import annotations

from datetime import timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from app.core.config import settings
from app.models.event import Event


def to_unified_event(event: Event) -> dict[str, Any]:
    """Convert the middleware MVP event shape to the AI UnifiedEvent contract."""
    event_type, source_layer, payload, severity = _map_event(event)
    ts = event.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    details = event.details
    return {
        "event_id": str(_stable_uuid(event.event_id)),
        "schema_version": "1.0.0",
        "event_type": event_type,
        "source_layer": source_layer,
        "timestamp": ts.isoformat(),
        "ingestion_timestamp": ts.isoformat(),
        "building_id": str(details.get("building_id", settings.BUILDING_ID)),
        "zone_id": str(details.get("zone_id", event.location)),
        "device_id": event.source_device,
        "user_id": details.get("user_id"),
        "severity_raw": str(details.get("severity_raw", severity)).upper(),
        "payload": payload,
        "correlated_events": [
            str(_stable_uuid(str(item)))
            for item in details.get("correlated_events", [])
        ],
    }


async def forward_event_to_ai(event: Event) -> None:
    """Best-effort forwarding; the middleware should keep accepting events."""
    if not settings.AI_FORWARD_ENABLED:
        return

    url = f"{settings.AI_ENGINE_URL.rstrip('/')}/api/ingest/events"
    payload = to_unified_event(event)
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


def _stable_uuid(value: str):
    return uuid5(NAMESPACE_URL, f"smart-intrusion-detection:{value}")


def _optional_uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return str(_stable_uuid(str(value)))


def _map_event(event: Event) -> tuple[str, str, dict[str, Any], str]:
    details = event.details
    event_type = event.event_type.value

    if event_type == "badge_access":
        return (
            "BADGE_ACCESS",
            "PHYSICAL",
            {
                "kind": "BADGE_ACCESS",
                "badge_id": str(details.get("badge_id", "unknown")),
                "reader_device_id": event.source_device,
                "access_result": _access_result(details),
                "door_id": details.get("door_id"),
            },
            "INFO",
        )

    if event_type == "door_sensor":
        state = str(details.get("state", "OPEN")).upper()
        door_id = str(details.get("door_id", event.source_device))
        if state == "FORCED":
            return (
                "DOOR_FORCED",
                "PHYSICAL",
                {
                    "kind": "DOOR_FORCED",
                    "door_id": door_id,
                    "state": "FORCED",
                    "no_badge_window_seconds": float(
                        details.get("no_badge_window_seconds", 10.0)
                    ),
                },
                "ALERT",
            )
        if state == "CLOSED":
            return (
                "DOOR_CLOSED",
                "PHYSICAL",
                {
                    "kind": "DOOR_CLOSED",
                    "door_id": door_id,
                    "state": "CLOSED",
                    "open_duration_seconds": details.get("open_duration_seconds"),
                },
                "INFO",
            )
        return (
            "DOOR_OPENED",
            "PHYSICAL",
            {
                "kind": "DOOR_OPENED",
                "door_id": door_id,
                "state": "OPEN",
                "associated_badge_event_id": _optional_uuid(
                    details.get("associated_badge_event_id")
                ),
            },
            "INFO",
        )

    if event_type == "motion_detected":
        return (
            "MOTION_DETECTED",
            "PHYSICAL",
            {
                "kind": "MOTION_DETECTED",
                "detector_device_id": event.source_device,
                "entity_count": int(details.get("entity_count", 1)),
            },
            "INFO",
        )

    if event_type == "network_anomaly":
        return (
            "NETWORK_ANOMALY",
            "CYBER",
            {
                "kind": "NETWORK_ANOMALY",
                "anomaly_label": str(details.get("anomaly_label", "UNKNOWN")).upper(),
                "src_ip": str(details.get("src_ip", "0.0.0.0")),
                "severity_hint": float(details.get("severity_hint", 0.7)),
            },
            "ALERT",
        )

    return (
        "NETWORK_FLOW",
        "CYBER",
        {
            "kind": "NETWORK_FLOW",
            "src_ip": str(details.get("src_ip", "0.0.0.0")),
            "dst_ip": str(details.get("dst_ip", "0.0.0.0")),
            "bytes_out": int(details.get("bytes_out", details.get("bytes_sent", 0))),
            "bytes_in": int(details.get("bytes_in", details.get("bytes_received", 0))),
            "distinct_dst_ports": int(details.get("distinct_dst_ports", 1)),
            "window_seconds": float(details.get("window_seconds", 60.0)),
        },
        "INFO",
    )


def _access_result(details: dict[str, Any]) -> str:
    raw = details.get("access_result", details.get("access", "GRANTED"))
    value = str(raw).upper()
    if value in {"GRANTED", "DENIED", "TIMEOUT"}:
        return value
    return "DENIED"
