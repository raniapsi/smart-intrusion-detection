"""
Scenario 4 — Revoked badge attempted access.

A formerly-employed user's badge is no longer valid, but someone is
trying to use it. Multiple BADGE_ACCESS events with access_result=DENIED
in quick succession on the same reader.

Discriminant time: end-of-day (when departing employees might attempt
re-entry) or after-hours.

Expected classification: CRITICAL (~0.80 per README section 12).
The repeated DENIED is unambiguous — a legitimate user wouldn't retry
3+ times in 30 seconds.
"""

from __future__ import annotations

from datetime import date, time

from schemas import AccessResult, AIClassification, BuildingTopology, UnifiedEvent

from ..generators.badge import make_badge_event
from ..generators.rng import Rng
from ..generators.timeline import at_offset, combine_utc
from .base import (
    InjectionResult,
    Scenario,
    Truth,
    merge_and_sort,
)


class RevokedBadgeScenario(Scenario):
    name = "revoked_badge"
    default_day = "2026-04-08"

    ATTACK_HOUR = 19
    ATTACK_MINUTE = 30
    TARGET_ZONE = "Z2"  # someone trying to re-enter the office after hours
    # Use a fictional badge_id NOT in topology — it has no associated user.
    REVOKED_BADGE_ID = "b999"
    N_ATTEMPTS = 5

    def inject(
        self,
        *,
        baseline: list[UnifiedEvent],
        topo: BuildingTopology,
        rng: Rng,
    ) -> InjectionResult:
        if baseline:
            d: date = baseline[0].timestamp.date()
        else:
            d = date.fromisoformat(self.default_day)

        attack_ts = combine_utc(d, time(self.ATTACK_HOUR, self.ATTACK_MINUTE, 0))

        from schemas import DeviceType
        reader_id = next(
            (dev.device_id for dev in topo.devices
             if dev.zone_id == self.TARGET_ZONE and dev.type == DeviceType.BADGE_READER),
            None,
        )
        if reader_id is None:
            raise RuntimeError(f"no reader in zone {self.TARGET_ZONE}")

        attack_events: list[UnifiedEvent] = []

        # N consecutive DENIED attempts, ~5 seconds apart
        for i in range(self.N_ATTEMPTS):
            ts = at_offset(attack_ts, i * 5.0 + rng.uniform(-1.0, 1.0))
            attack_events.append(make_badge_event(
                timestamp=ts,
                building_id=topo.building_id,
                zone_id=self.TARGET_ZONE,
                reader_device_id=reader_id,
                badge_id=self.REVOKED_BADGE_ID,
                user_id=None,  # unknown badge, no user attached
                access_result=AccessResult.DENIED,
                door_id=None,
            ))

        truth = Truth(
            scenario=self.name,
            description=(
                f"Unknown badge {self.REVOKED_BADGE_ID} attempted access to "
                f"{self.TARGET_ZONE} {self.N_ATTEMPTS} times in ~25 seconds, "
                f"all DENIED."
            ),
            attack_event_ids=[ev.event_id for ev in attack_events],
            attack_window_start=attack_ts,
            attack_window_end=at_offset(attack_ts, self.N_ATTEMPTS * 5.0 + 5.0),
            target_zone=self.TARGET_ZONE,
            target_user=None,
            expected_classification=AIClassification.CRITICAL,
            expected_min_score=0.75,
            expected_detectors=["rule:repeated_denied"],
        )

        return InjectionResult(
            events=merge_and_sort(baseline, attack_events),
            truth=truth,
        )