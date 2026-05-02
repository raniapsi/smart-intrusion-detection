"""
Isolation Forest anomaly detector.

Wraps scikit-learn's IsolationForest with project conventions:
  - inputs come from the `features` DataFrame schema
  - the trained model is persisted alongside the feature column list it
    was trained on (so prediction time can validate column alignment)
  - the raw IF score is mapped to [0, 1] via a calibrated sigmoid

Why a sigmoid and not just min-max?
  scikit-learn's `decision_function` returns values where:
    - positive = inlier (normal)
    - negative = outlier (anomalous)
    - magnitude is in arbitrary units depending on the dataset
  We calibrate by fitting a sigmoid on the TRAINING distribution: the
  median decision becomes 0.0 in our normalised score, the 1st
  percentile (very anomalous training points) becomes ~0.5, and
  scores below the training minimum saturate to ~1.0. This makes
  the IF output directly comparable with the rules engine output.

NaN handling:
  scikit-learn's IsolationForest tolerates NaN since 1.4. We pass
  features through unchanged. For columns where NaN means "not
  applicable" (e.g. bytes_out for non-network events), the IF treats
  them as a separate signal — which is what we want.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from features import GROUPS


# Default hyperparameters. Conservative for our scale (~hundreds of
# thousands of training samples). contamination=0.01 means we tell IF
# to expect ~1% anomalies in the training set, which is a generous
# upper bound: our baseline is supposed to be clean.
DEFAULT_N_ESTIMATORS: int = 200
DEFAULT_CONTAMINATION: float = 0.01
DEFAULT_RANDOM_STATE: int = 42


@dataclass
class TrainedIsolationForest:
    """
    Trained model bundle: the sklearn estimator, the feature column list,
    and the calibration parameters needed to map decision_function to
    a score in [0, 1].
    """

    model: IsolationForest
    feature_columns: list[str]
    # Calibration: we map decision_function(x) through a logistic so that
    # `decision_at_p_normal` (the median of training decisions, ~the most
    # "normal" decision) maps to 0.0 score, and `decision_at_p_outlier`
    # (the 1st percentile, the most extreme inliers we saw) maps to 0.5.
    # Below decision_at_p_outlier the score asymptotes to 1.0.
    decision_at_p_normal: float = 0.0
    decision_at_p_outlier: float = 0.0

    # Bookkeeping for reproducibility.
    n_train_samples: int = 0
    contamination: float = DEFAULT_CONTAMINATION
    n_estimators: int = DEFAULT_N_ESTIMATORS

    def score(self, df: pd.DataFrame) -> np.ndarray:
        """
        Compute the IF score in [0, 1] for each row of df.

        df must contain (a superset of) self.feature_columns. Other columns
        are ignored. We DO NOT modify df.
        """
        missing = [c for c in self.feature_columns if c not in df.columns]
        if missing:
            raise KeyError(f"Missing feature columns: {missing}")

        X = df[self.feature_columns].to_numpy(dtype=np.float32, copy=False)
        decisions = self.model.decision_function(X)
        return _decision_to_score(
            decisions,
            normal=self.decision_at_p_normal,
            outlier=self.decision_at_p_outlier,
        )

    # ---- persistence --------------------------------------------------------

    def save(self, path: Path) -> None:
        """
        Persist as a joblib bundle. Path should end in .joblib.
        Also writes a sidecar .meta.json with non-sklearn metadata (handy
        for inspecting from outside Python).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "feature_columns": self.feature_columns,
                "decision_at_p_normal": self.decision_at_p_normal,
                "decision_at_p_outlier": self.decision_at_p_outlier,
                "n_train_samples": self.n_train_samples,
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
            },
            path,
        )
        # Sidecar metadata
        meta_path = path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps({
            "feature_columns": self.feature_columns,
            "decision_at_p_normal": self.decision_at_p_normal,
            "decision_at_p_outlier": self.decision_at_p_outlier,
            "n_train_samples": self.n_train_samples,
            "contamination": self.contamination,
            "n_estimators": self.n_estimators,
        }, indent=2))

    @classmethod
    def load(cls, path: Path) -> "TrainedIsolationForest":
        bundle = joblib.load(Path(path))
        return cls(**bundle)


# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------

def train_isolation_forest(
    df: pd.DataFrame,
    *,
    feature_columns: Optional[list[str]] = None,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    contamination: float = DEFAULT_CONTAMINATION,
    random_state: int = DEFAULT_RANDOM_STATE,
    max_samples: int | str = "auto",
) -> TrainedIsolationForest:
    """
    Fit an IsolationForest on the given feature DataFrame.

    Args:
        df: feature DataFrame (output of FeatureExtractor). Should be
            "normal" data — the model assumes it.
        feature_columns: which columns to use. Defaults to GROUPS.numeric_for_if.
        n_estimators: number of trees in the forest.
        contamination: expected fraction of outliers in training data.
        random_state: for reproducibility.
        max_samples: per-tree subsample size (sklearn's default 'auto'
            uses min(256, n_samples)).
    """
    if feature_columns is None:
        feature_columns = GROUPS.numeric_for_if
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise KeyError(f"Missing feature columns for training: {missing}")

    X = df[feature_columns].to_numpy(dtype=np.float32, copy=False)
    n = X.shape[0]
    if n < 100:
        raise ValueError(
            f"Refusing to train on {n} samples — need at least 100."
        )

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        max_samples=max_samples,
        n_jobs=-1,
    )
    model.fit(X)

    # Calibrate score mapping using the TRAINING decisions:
    # - normal anchor: median of training decisions (most "normal" point)
    # - outlier anchor: 1st percentile (most extreme of the training set)
    decisions = model.decision_function(X)
    normal_anchor = float(np.median(decisions))
    outlier_anchor = float(np.percentile(decisions, 1))

    return TrainedIsolationForest(
        model=model,
        feature_columns=list(feature_columns),
        decision_at_p_normal=normal_anchor,
        decision_at_p_outlier=outlier_anchor,
        n_train_samples=n,
        contamination=contamination,
        n_estimators=n_estimators,
    )


# -----------------------------------------------------------------------------
# Score mapping
# -----------------------------------------------------------------------------

def _decision_to_score(
    decisions: np.ndarray, *, normal: float, outlier: float
) -> np.ndarray:
    """
    Map sklearn decision_function values to a [0, 1] anomaly score.

    Uses a logistic curve calibrated so that:
      - decision = `normal` (the median normal decision) -> score = 0.0
      - decision = `outlier` (the 1st-percentile of training) -> score = 0.5
      - decision << `outlier` -> score -> 1.0

    The sigmoid steepness `k` is chosen to give a smooth-but-decisive
    curve: distance of (normal - outlier) gets us most of the way.
    """
    delta = normal - outlier
    if delta <= 0:
        # Degenerate calibration: fall back to a flat 0.0 score.
        return np.zeros_like(decisions, dtype=np.float32)

    # Steepness: 4/delta gives a sigmoid that crosses 0.5 at `outlier`
    # and ~0.95 at `outlier - delta`.
    k = 4.0 / delta
    # We want score increasing as decision DECREASES (more anomalous):
    # so use sigmoid(k * (outlier - decision)) which gives 0.5 at decision=outlier.
    z = k * (outlier - decisions)
    # Numerically stable sigmoid.
    s = np.where(
        z >= 0,
        1.0 / (1.0 + np.exp(-z)),
        np.exp(z) / (1.0 + np.exp(z)),
    )
    return s.astype(np.float32)