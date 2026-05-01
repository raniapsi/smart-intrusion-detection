"""
Dataset generators.

Public API: build events from contexts, all backed by a reproducible RNG.
"""

from .badge import make_badge_event
from .door import (
    make_door_closed_event,
    make_door_forced_event,
    make_door_opened_event,
)
from .motion import make_motion_event
from .network import (
    WINDOW_SECONDS,
    build_camera_baselines,
    generate_camera_flow,
    generate_network_flows_for_day,
)
from .orchestrator import generate_baseline, generate_day
from .rng import Rng
from .timeline import UTC, combine_utc, is_weekend
from .user_day import generate_user_day

__all__ = [
    # User-day orchestration
    "generate_user_day",
    # Multi-user / multi-day orchestration
    "generate_day",
    "generate_baseline",
    # Network layer
    "generate_camera_flow",
    "generate_network_flows_for_day",
    "build_camera_baselines",
    "WINDOW_SECONDS",
    # Low-level event makers (for scenarios in 2c)
    "make_badge_event",
    "make_door_opened_event",
    "make_door_closed_event",
    "make_door_forced_event",
    "make_motion_event",
    # Utilities
    "Rng",
    "UTC",
    "combine_utc",
    "is_weekend",
]
