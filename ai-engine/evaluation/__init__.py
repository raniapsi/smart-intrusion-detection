"""
ai-engine evaluation package.

Metrics computed against the ground-truth `.truth.json` of each scenario.
"""

from .metrics import (
    DetectionMetrics,
    evaluate,
    evaluate_thresholds,
    load_truth,
    metrics_to_dataframe,
)

__all__ = [
    "DetectionMetrics",
    "evaluate",
    "evaluate_thresholds",
    "load_truth",
    "metrics_to_dataframe",
]