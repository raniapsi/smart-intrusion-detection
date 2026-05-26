"""
ai-engine fusion package.

Combines per-detector scores into a final classification, with an
explicit physical/cyber correlation bonus.
"""

from .correlator import (
    DEFAULT_MIN_PEER_SCORE,
    DEFAULT_WINDOW_SECONDS,
    correlate_physical_cyber,
)
from .scorer import DEFAULT_CORRELATION_WEIGHT, fuse_scores

__all__ = [
    "fuse_scores",
    "correlate_physical_cyber",
    "DEFAULT_CORRELATION_WEIGHT",
    "DEFAULT_WINDOW_SECONDS",
    "DEFAULT_MIN_PEER_SCORE",
]