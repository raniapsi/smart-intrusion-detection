"""
Evaluation metrics for the AI engine.

Given:
  - a feature DataFrame with an `event_id` column and a score column
  - a Truth (loaded from a scenario's `.truth.json`)

We compute classic detection metrics:
  - true positives (TP): events scored above threshold AND in truth.attack_event_ids
  - false positives (FP): scored above threshold AND NOT in truth
  - false negatives (FN): in truth but scored below threshold
  - precision, recall, F1
  - "scenario detected": True iff at least one TP exists with score >=
    truth.expected_min_score (the per-scenario success criterion)

These metrics are computed AT a chosen score threshold. Higher
thresholds reduce FP at the cost of recall. The README's mapping
gives us natural thresholds: 0.3 (SUSPECT cut-in), 0.7 (CRITICAL cut-in).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class DetectionMetrics:
    """Metrics for one (scenario, score column, threshold) triple."""

    scenario: str
    score_column: str
    threshold: float
    n_events_total: int
    n_attack_events: int
    n_predicted_positive: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    scenario_detected: bool         # at least one TP at expected_min_score
    max_attack_score: float         # max score across attack events
    max_normal_score: float         # max score across non-attack events


def evaluate(
    *,
    df_features: pd.DataFrame,
    score_column: str,
    truth: dict,
    threshold: float,
) -> DetectionMetrics:
    """
    Run one evaluation pass.

    Args:
        df_features: must have `event_id` (string) and `score_column`.
        score_column: name of the score column in df_features.
        truth: parsed `.truth.json` (dict — see Truth.to_dict()).
        threshold: classify as "predicted positive" iff score >= threshold.
    """
    if score_column not in df_features.columns:
        raise KeyError(f"score column '{score_column}' not in features")

    if "event_id" not in df_features.columns:
        raise KeyError("features must contain an event_id column")

    attack_ids = set(truth.get("attack_event_ids", []))
    expected_min_score = float(truth.get("expected_min_score", 0.7))
    scenario = truth.get("scenario", "unknown")

    is_attack = df_features["event_id"].isin(attack_ids)
    score = df_features[score_column].astype(float)
    predicted = score >= threshold

    tp = int((is_attack & predicted).sum())
    fp = int((~is_attack & predicted).sum())
    fn = int((is_attack & ~predicted).sum())
    n_pred_pos = int(predicted.sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )

    # Did at least one attack event reach the expected_min_score?
    if is_attack.any():
        max_attack_score = float(score[is_attack].max())
    else:
        max_attack_score = 0.0
    scenario_detected = max_attack_score >= expected_min_score

    if (~is_attack).any():
        max_normal_score = float(score[~is_attack].max())
    else:
        max_normal_score = 0.0

    return DetectionMetrics(
        scenario=scenario,
        score_column=score_column,
        threshold=threshold,
        n_events_total=len(df_features),
        n_attack_events=int(is_attack.sum()),
        n_predicted_positive=n_pred_pos,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        scenario_detected=scenario_detected,
        max_attack_score=max_attack_score,
        max_normal_score=max_normal_score,
    )


def evaluate_thresholds(
    *,
    df_features: pd.DataFrame,
    score_column: str,
    truth: dict,
    thresholds: Iterable[float] = (0.3, 0.5, 0.7),
) -> list[DetectionMetrics]:
    """Convenience: run evaluate() for several thresholds, in order."""
    return [
        evaluate(
            df_features=df_features,
            score_column=score_column,
            truth=truth,
            threshold=t,
        )
        for t in thresholds
    ]


def metrics_to_dataframe(metrics: list[DetectionMetrics]) -> pd.DataFrame:
    """Pretty-print helper. Produces one row per metric."""
    return pd.DataFrame([asdict(m) for m in metrics])


def load_truth(path: Path) -> dict:
    """Load a `.truth.json` file as a plain dict."""
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)