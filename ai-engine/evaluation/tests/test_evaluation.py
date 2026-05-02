"""
Tests for the evaluation metrics module.
"""

from __future__ import annotations

import pandas as pd
import pytest

from evaluation import evaluate, evaluate_thresholds, metrics_to_dataframe


def _make_df(scores_and_attack: list[tuple[float, bool]]) -> pd.DataFrame:
    """Helper: build a small DataFrame with explicit scores and attack flags."""
    rows = []
    for i, (score, is_attack) in enumerate(scores_and_attack):
        rows.append({
            "event_id": f"id-{i}",
            "score_x": score,
            "_is_attack": is_attack,
        })
    return pd.DataFrame(rows)


def _make_truth(df: pd.DataFrame, expected_min_score: float = 0.7) -> dict:
    return {
        "scenario": "test",
        "attack_event_ids": [
            row["event_id"] for _, row in df[df["_is_attack"]].iterrows()
        ],
        "expected_min_score": expected_min_score,
    }


class TestEvaluate:

    def test_perfect_classifier(self):
        df = _make_df([
            (0.9, True),   # TP
            (0.8, True),   # TP
            (0.1, False),  # TN
            (0.2, False),  # TN
        ])
        truth = _make_truth(df)
        m = evaluate(df_features=df, score_column="score_x",
                     truth=truth, threshold=0.5)
        assert m.true_positives == 2
        assert m.false_positives == 0
        assert m.false_negatives == 0
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.f1 == 1.0
        assert m.scenario_detected is True

    def test_threshold_too_high_misses_attacks(self):
        df = _make_df([
            (0.4, True),   # FN at threshold 0.5
            (0.1, False),  # TN
        ])
        truth = _make_truth(df, expected_min_score=0.5)
        m = evaluate(df_features=df, score_column="score_x",
                     truth=truth, threshold=0.5)
        assert m.true_positives == 0
        assert m.false_negatives == 1
        assert m.recall == 0.0
        assert m.scenario_detected is False  # max attack 0.4 < 0.5

    def test_false_positives(self):
        df = _make_df([
            (0.9, True),   # TP
            (0.8, False),  # FP
            (0.7, False),  # FP
        ])
        truth = _make_truth(df)
        m = evaluate(df_features=df, score_column="score_x",
                     truth=truth, threshold=0.5)
        assert m.true_positives == 1
        assert m.false_positives == 2
        assert m.precision == 1.0 / 3.0
        assert m.recall == 1.0

    def test_no_attacks_in_truth(self):
        df = _make_df([
            (0.9, False),
            (0.1, False),
        ])
        truth = _make_truth(df)
        m = evaluate(df_features=df, score_column="score_x",
                     truth=truth, threshold=0.5)
        assert m.true_positives == 0
        assert m.false_negatives == 0
        # No attacks at all -> recall is undefined; we set 0.
        assert m.recall == 0.0

    def test_threshold_sweep(self):
        df = _make_df([
            (0.9, True), (0.6, True), (0.4, True),
            (0.5, False), (0.2, False), (0.1, False),
        ])
        truth = _make_truth(df)
        results = evaluate_thresholds(
            df_features=df, score_column="score_x",
            truth=truth, thresholds=(0.3, 0.5, 0.7),
        )
        # at 0.3: all 3 attacks caught, but 2 FPs (0.5 and 0.2 — no, 0.2 < 0.3)
        # Actually: scores >= 0.3 are: 0.9 (TP), 0.6 (TP), 0.4 (TP), 0.5 (FP)
        m_low = results[0]
        assert m_low.true_positives == 3
        assert m_low.false_positives == 1

        # at 0.7: only 0.9 is >= 0.7 (TP). 0.6 and 0.4 become FNs.
        m_high = results[2]
        assert m_high.true_positives == 1
        assert m_high.false_negatives == 2


class TestMetricsDataFrame:

    def test_to_dataframe(self):
        df = _make_df([(0.9, True), (0.1, False)])
        truth = _make_truth(df)
        ms = evaluate_thresholds(
            df_features=df, score_column="score_x",
            truth=truth, thresholds=(0.5,),
        )
        out = metrics_to_dataframe(ms)
        assert isinstance(out, pd.DataFrame)
        assert "precision" in out.columns
        assert len(out) == 1