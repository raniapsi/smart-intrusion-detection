"""
Build an Alert from an EnrichedEvent.

The Alert schema (see schemas/alerts.py) expects:
  - a triggering_event_id
  - a human-readable title and description
  - a list of contributing_detectors
  - optionally a suggested_action

This module turns the structured signals into nice strings. It runs once
per non-NORMAL event and is therefore not performance-critical, so we
can spend a bit of code on producing helpful messages.
"""

from __future__ import annotations

from typing import Optional

from schemas import AIClassification, Alert, EnrichedEvent, EventType


# -----------------------------------------------------------------------------
# Title templates by event_type. Keep these short — the dashboard truncates.
# -----------------------------------------------------------------------------

_TITLE_TEMPLATES: dict[EventType, str] = {
    EventType.DOOR_FORCED:     "Door {door} forced in zone {zone}",
    EventType.DOOR_OPENED:     "Door event in zone {zone}",
    EventType.DOOR_CLOSED:     "Door event in zone {zone}",
    EventType.BADGE_ACCESS:    "Badge access in zone {zone}",
    EventType.MOTION_DETECTED: "Motion event in zone {zone}",
    EventType.NETWORK_FLOW:    "Network anomaly from {device}",
    EventType.NETWORK_ANOMALY: "Network anomaly from {device}",
    EventType.CAMERA_EVENT:    "Camera event in zone {zone}",
    EventType.DEVICE_STATUS:   "Device status alert: {device}",
}


# Suggested actions, indexed by which rule fired (when no rule fires we
# leave the suggestion empty — the SOC operator decides).
_SUGGESTED_ACTIONS: dict[str, str] = {
    "rule:door_forced":       "lock_door:{door} ; alert_security",
    "rule:repeated_denied":   "block_badge ; review_camera_footage",
    "rule:port_scan":         "isolate_vlan ; capture_traffic",
    "rule:exfiltration":      "isolate_device ; capture_traffic",
    "rule:tailgating":        "review_camera_footage",
    "rule:off_hours_restricted": "review_camera_footage ; verify_user_intent",
    "rule:network_anomaly":   "isolate_device ; capture_traffic",
}


def _extract_door_id(enriched: EnrichedEvent) -> Optional[str]:
    """Pull a door_id from the payload when present."""
    payload = enriched.payload
    for attr in ("door_id",):
        v = getattr(payload, attr, None)
        if v is not None:
            return v
    return None


def build_alert_from_enriched(
    *,
    enriched: EnrichedEvent,
    rule_hits: Optional[str],
    score_if: float,
    score_rules: float,
    correlation_peer: float,
) -> Alert:
    """
    Construct an Alert from an EnrichedEvent. Caller decides whether to emit
    it (based on classification != NORMAL) — this builder doesn't gate.

    Args:
        enriched: the source event with AI fields populated
        rule_hits: pipe-separated rule labels that fired, or None
        score_if: raw IF contribution
        score_rules: raw rules contribution
        correlation_peer: peer score from the cross-layer correlator
    """
    door = _extract_door_id(enriched) or "?"
    template = _TITLE_TEMPLATES.get(
        enriched.event_type, "Event in zone {zone}"
    )
    title = template.format(
        door=door,
        zone=enriched.zone_id,
        device=enriched.device_id,
    )

    # Description: include the score, the dominant signal, and any user.
    description_parts = [
        f"Classification: {enriched.ai_classification.value}",
        f"Score: {enriched.ai_score:.2f}",
    ]
    if score_rules > score_if:
        description_parts.append(f"Driver: rules ({score_rules:.2f})")
    elif score_if > 0:
        description_parts.append(f"Driver: behavioural model ({score_if:.2f})")
    if correlation_peer > 0:
        description_parts.append(
            f"Cross-layer correlation peer: {correlation_peer:.2f}"
        )
    if enriched.user_id is not None:
        description_parts.append(f"User: {enriched.user_id}")
    description = " | ".join(description_parts)

    # Detectors that contributed: union of fired rules + (if score_if > 0.3) IF.
    contributing: list[str] = []
    if rule_hits:
        contributing.extend(
            label for label in rule_hits.split("|") if label
        )
    if score_if >= 0.3:
        contributing.append("if:behaviour")
    if correlation_peer > 0:
        contributing.append("fusion:phys_cyber_corr")

    # Suggested action: take the first matching rule's recommendation.
    suggested: Optional[str] = None
    if rule_hits:
        for label in rule_hits.split("|"):
            tmpl = _SUGGESTED_ACTIONS.get(label)
            if tmpl is not None:
                suggested = tmpl.format(door=door)
                break

    return Alert(
        triggering_event_id=enriched.event_id,
        building_id=enriched.building_id,
        zone_id=enriched.zone_id,
        user_id=enriched.user_id,
        classification=enriched.ai_classification,
        score=enriched.ai_score,
        title=title,
        description=description,
        contributing_detectors=contributing,
        suggested_action=suggested,
    )