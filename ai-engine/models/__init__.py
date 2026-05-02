"""
ai-engine models package.

Detection models that produce a [0, 1] anomaly score from feature DataFrames.
"""

from .isolation_forest import (
    DEFAULT_CONTAMINATION,
    DEFAULT_N_ESTIMATORS,
    DEFAULT_RANDOM_STATE,
    TrainedIsolationForest,
    train_isolation_forest,
)
from .rules_engine import ALL_RULES, Rule, score_rules

__all__ = [
    # Isolation Forest
    "TrainedIsolationForest",
    "train_isolation_forest",
    "DEFAULT_N_ESTIMATORS",
    "DEFAULT_CONTAMINATION",
    "DEFAULT_RANDOM_STATE",
    # Rules engine
    "Rule",
    "ALL_RULES",
    "score_rules",
]