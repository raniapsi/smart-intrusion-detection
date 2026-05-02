"""
Fusion scorer.

Combines the per-event scores from the rules engine, the Isolation Forest,
and the cross-layer correlator into a single `score_final` in [0, 1].

Formula (decided at step 5):

    score_combined = max(score_rules, score_if)
    score_correlation_bonus = correlation_weight × score_correlation_peer
    score_final = min(1.0, score_combined + score_correlation_bonus × (1 - score_combined))

Properties of this formula:
  - score_final is always >= score_combined (correlation can only push UP)
  - score_final is bounded by 1.0
  - The bonus is PROPORTIONAL TO THE MARGIN: an event already at 0.95 only
    receives a small bonus, an event at 0.50 receives a larger one. This
    matches the intuition that correlation should turn "suspect" into
    "critical", not push "barely-noise" into the alert range.
  - When score_correlation_peer = 0 (no correlated event found), the
    bonus is 0 and score_final = score_combined.

Classification mapping (from README section 7.3):
    [0.0, 0.3)  -> NORMAL
    [0.3, 0.7)  -> SUSPECT
    [0.7, 1.0]  -> CRITICAL
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .correlator import (
    DEFAULT_MIN_PEER_SCORE,
    DEFAULT_WINDOW_SECONDS,
    correlate_physical_cyber,
)


# Default weight applied to the correlation peer score.
# 0.30 means a correlated peer at score 1.0 contributes a bonus of 0.30
# to the residual margin. With a 0.50 base score that adds up to:
#   0.50 + 0.30 × (1 - 0.50) = 0.50 + 0.15 = 0.65 (just under SUSPECT/CRITICAL)
# With a 0.85 base score:
#   0.85 + 0.30 × (1 - 0.85) = 0.85 + 0.045 = 0.895 (well into CRITICAL)
DEFAULT_CORRELATION_WEIGHT: float = 0.30


def fuse_scores(
    df: pd.DataFrame,
    *,
    correlation_weight: float = DEFAULT_CORRELATION_WEIGHT,
    correlation_window_seconds: float = DEFAULT_WINDOW_SECONDS,
    correlation_min_peer: float = DEFAULT_MIN_PEER_SCORE,
) -> pd.DataFrame:
    """
    Compute the fused score for each row.

    Args:
        df: must contain `timestamp`, `source_layer`, `zone_id`,
            `score_rules`, `score_if`.
        correlation_weight: how much the correlation peer score boosts.
        correlation_window_seconds: time window for correlation lookup.
        correlation_min_peer: ignore peer events with score below this.

    Returns:
        DataFrame with the SAME index as df, containing four new columns:
          - score_combined: max(score_rules, score_if)
          - score_correlation_peer: best peer score in opposite layer
          - score_final: combined + bonus, clipped to [0, 1]
          - ai_classification: NORMAL / SUSPECT / CRITICAL based on score_final
    """
    required = {"score_rules", "score_if", "timestamp", "source_layer", "zone_id"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"fuse_scores missing columns: {missing}")

    rules = df["score_rules"].astype(np.float32).to_numpy()
    iforest = df["score_if"].astype(np.float32).to_numpy()
    score_combined = np.maximum(rules, iforest)

    # Step 1: compute the correlation peer score using `score_combined`.
    # We pass the per-event combined score as the input — the correlator
    # uses this both for the threshold (min_peer_score) and as the value
    # returned for matching peers.
    df_with_combined = df.copy()
    df_with_combined["score_combined"] = score_combined
    peer = correlate_physical_cyber(
        df_with_combined,
        score_column="score_combined",
        window_seconds=correlation_window_seconds,
        min_peer_score=correlation_min_peer,
    ).to_numpy(dtype=np.float32)

    # Step 2: bonus = weight × peer × (1 - combined)
    bonus = correlation_weight * peer * (1.0 - score_combined)
    score_final = np.clip(score_combined + bonus, 0.0, 1.0).astype(np.float32)

    # Step 3: classification mapping
    classification = np.where(
        score_final >= 0.7, "CRITICAL",
        np.where(score_final >= 0.3, "SUSPECT", "NORMAL"),
    )

    out = pd.DataFrame({
        "score_combined": score_combined,
        "score_correlation_peer": peer,
        "score_final": score_final,
        "ai_classification": pd.Series(classification, index=df.index, dtype="string"),
    }, index=df.index)
    return out