"""
Base infrastructure for attack scenarios.

A Scenario takes a baseline day and INJECTS attack events into it.
The output is:
  - a list of UnifiedEvent objects (baseline + attack, sorted by timestamp)
  - a Truth object describing what was injected (for evaluation in step 4)

Each scenario subclasses Scenario and implements `inject()`.

Design choice: scenarios receive a fully-formed baseline day rather than
generating their own. This guarantees the attack happens against realistic
background traffic (correlations only fire if there's network activity to
correlate with), and lets us mix-and-match scenarios on the same baseline.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

from schemas import AIClassification, BuildingTopology, UnifiedEvent

from ..generators.rng import Rng


# -----------------------------------------------------------------------------
# Truth — ground truth for one injected attack
# -----------------------------------------------------------------------------

@dataclass
class Truth:
    """
    Ground truth metadata for one attack scenario.

    Persisted alongside the events JSONL as `<scenario>.truth.json` and
    consumed at step 4 (model evaluation) to compute precision/recall.
    """

    scenario: str                          # short identifier, e.g. "forced_door"
    description: str                       # human-readable one-liner
    attack_event_ids: list[UUID] = field(default_factory=list)
    attack_window_start: Optional[datetime] = None
    attack_window_end: Optional[datetime] = None
    target_zone: Optional[str] = None
    target_user: Optional[str] = None
    expected_classification: AIClassification = AIClassification.SUSPECT
    expected_min_score: float = 0.3
    expected_detectors: list[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serialisable dict (UUIDs → str, datetimes → ISO)."""
        d = asdict(self)
        d["attack_event_ids"] = [str(uid) for uid in self.attack_event_ids]
        if self.attack_window_start:
            d["attack_window_start"] = self.attack_window_start.isoformat()
        if self.attack_window_end:
            d["attack_window_end"] = self.attack_window_end.isoformat()
        # asdict() converts the enum to its dataclass form; force the string.
        d["expected_classification"] = self.expected_classification.value
        return d

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=False)


# -----------------------------------------------------------------------------
# Scenario base class
# -----------------------------------------------------------------------------

@dataclass
class InjectionResult:
    """Tuple of (final_events, truth) returned by Scenario.inject()."""

    events: list[UnifiedEvent]
    truth: Truth


class Scenario(ABC):
    """
    Abstract base for an attack scenario.

    Concrete scenarios provide:
      - `name`: short identifier used in CLI and truth.json
      - `default_day`: the day they prefer (most discriminant for them)
      - `inject(baseline, topo, rng)`: returns the (events, truth) tuple
    """

    name: str = "abstract"
    default_day: str = "2026-04-08"   # a Wednesday

    @abstractmethod
    def inject(
        self,
        *,
        baseline: list[UnifiedEvent],
        topo: BuildingTopology,
        rng: Rng,
    ) -> InjectionResult:
        """
        Insert attack events into a baseline list.

        Implementations MUST:
          - return events sorted by timestamp
          - record every injected event_id in truth.attack_event_ids
          - set attack_window_start/end to bound the attack temporally
        """
        raise NotImplementedError


# -----------------------------------------------------------------------------
# Helpers shared by scenarios
# -----------------------------------------------------------------------------

def merge_and_sort(
    baseline: list[UnifiedEvent], injected: list[UnifiedEvent]
) -> list[UnifiedEvent]:
    """Concatenate two event lists and sort by timestamp."""
    merged = list(baseline) + list(injected)
    merged.sort(key=lambda e: e.timestamp)
    return merged


def first_user_outside_zone(
    topo: BuildingTopology, zone_id: str
) -> Optional[str]:
    """
    Pick the first user in the topology whose typical_zones do NOT include
    the given zone. Useful for "user X badged into Z but never goes to Z" attacks.
    """
    for u in topo.users:
        if zone_id not in u.typical_zones:
            return u.user_id
    return None


def find_camera_in_zone(topo: BuildingTopology, zone_id: str) -> Optional[str]:
    """Return the device_id of the first camera in `zone_id`, or None."""
    from schemas import DeviceType
    for d in topo.devices:
        if d.zone_id == zone_id and d.type == DeviceType.CAMERA:
            return d.device_id
    return None


def find_door_to_zone(topo: BuildingTopology, zone_id: str):
    """Return the first Door object leading to `zone_id`, or None."""
    for door in topo.doors:
        if door.zone_id == zone_id:
            return door
    return None