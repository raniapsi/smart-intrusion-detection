"""
Attack scenarios.

Each scenario is a class deriving from Scenario that injects attack 
events into a baseline day. Scenarios are registred in REGISTRY for 
CLI dispatch
"""

from .badge_off_hours import BadgeOffHoursScenario
from .base import InjectionResult, Scenario, Truth
from .camera_compromise import CameraCompromiseScenario
from .credential_theft import CredentialTheftScenario
from .forced_door import ForcedDoorScenario
from .hybrid_intrusion import HybridIntrusionScenario
from .revoked_badge import RevokedBadgeScenario
from .tailgating import TailgatingScenario

# Public Registry - CLI use this to dispatch by  --scenario name.
REGISTRY: dict[str, type[Scenario]] = {
    BadgeOffHoursScenario.name: BadgeOffHoursScenario,
    CameraCompromiseScenario.name: CameraCompromiseScenario,
    CredentialTheftScenario.name: CredentialTheftScenario,
    ForcedDoorScenario.name: ForcedDoorScenario,
    HybridIntrusionScenario.name: HybridIntrusionScenario,
    RevokedBadgeScenario.name: RevokedBadgeScenario,
    TailgatingScenario.name: TailgatingScenario,
}

__all__ = [
    "Scenario",
    "Truth",
    "InjectionResult",
    "REGISTRY",
    "BadgeOffHoursScenario",
    "ForcedDoorScenario",
    "TailgatingScenario",
    "RevokedBadgeScenario",
    "HybridIntrusionScenario",
    "CameraCompromiseScenario",
    "CredentialTheftScenario"
]