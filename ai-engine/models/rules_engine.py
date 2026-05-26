"""
Deterministic rules engine.

Rules are explainable, fast, and capture domain knowledge that ML
shouldn't have to "discover". They run as a Pandas operation per
feature DataFrame, returning a `score_rules` column ∈ [0, 1] plus a
`rule_hits` column listing which rule(s) fired.

Each rule produces:
  - a contribution (a float in [0, 1])
  - a rule label (e.g. "rule:door_forced")

The final score for a row is the MAX of all rule contributions on that
row. Max (rather than sum) is the right operator: rules don't compound,
they each independently say "I think this is suspicious to degree X".
A row that fires two 0.8 rules isn't more suspicious than a row that
fires one 0.8 rule.

Each rule is a pure function (DataFrame → Series of contributions),
so adding/removing rules is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


# A rule is a callable: DataFrame -> (contribution Series of floats in [0,1])
RuleFn = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Rule:
    """One named deterministic rule."""

    label: str          # e.g. "rule:door_forced" — used in expected_detectors
    fn: RuleFn          # df -> Series of float contributions

    def apply(self, df: pd.DataFrame) -> pd.Series:
        raw = self.fn(df)
        # Rules may return either pd.Series or np.ndarray. Coerce to a
        # Series indexed on df.index so downstream code can rely on alignment,
        # and so .clip(lower=, upper=) works (numpy's clip uses different kwargs).
        if not isinstance(raw, pd.Series):
            raw = pd.Series(raw, index=df.index, dtype="float32")
        return raw.clip(lower=0.0, upper=1.0)


# -----------------------------------------------------------------------------
# Individual rules
# -----------------------------------------------------------------------------

def _rule_door_forced(df: pd.DataFrame) -> pd.Series:
    """
    DOOR_FORCED is, by construction in our schema, never a normal event.
    A forced door without a badge is the canonical break-in signal.
    Contribution: 0.85 (high but not 1.0, leaving room for fusion to push
    higher when correlated with cyber signals).
    """
    return np.where(
        df["event_type"] == "DOOR_FORCED",
        0.85,
        0.0,
    )


def _rule_repeated_denied_badge(df: pd.DataFrame) -> pd.Series:
    """
    A DENIED badge attempt with >= 3 prior DENIED in the last 5 minutes
    on the same user/badge looks like a brute-force or revoked-badge use.
    Contribution scales: 3 attempts = 0.6, 5+ = 0.85.
    """
    is_denied = (
        (df["event_type"] == "BADGE_ACCESS")
        & (df["denied_badges_user_last_5min"] >= 2)
        # >= 2 priors + this event = >= 3 attempts in 5 min
    )
    # Linear ramp: 2 priors -> 0.6, 4 priors -> 0.85, capped.
    contribution = np.clip(
        0.30 + (df["denied_badges_user_last_5min"] - 1) * 0.15,
        0.0, 0.85,
    )
    return np.where(is_denied, contribution, 0.0)


def _rule_off_hours_restricted(df: pd.DataFrame) -> pd.Series:
    """
    Badge access outside the user's typical hours, in a RESTRICTED or
    CRITICAL zone. This is the badge_off_hours scenario signal.

    The IF should also catch this from features, but a deterministic rule
    gives us an explainable hit even before the model is trained.
    """
    cond = (
        (df["event_type"] == "BADGE_ACCESS")
        & (df["is_within_typical_hours"] == 0)
        & (df["zone_sensitivity_lvl"] >= 2)  # RESTRICTED (2) or CRITICAL (3)
        & (df["user_id"].notna())
    )
    # CRITICAL gets a higher score than RESTRICTED.
    contribution = np.where(
        df["zone_sensitivity_lvl"] >= 3, 0.55, 0.45,
    )
    return np.where(cond, contribution, 0.0)


def _rule_tailgating(df: pd.DataFrame) -> pd.Series:
    """
    MOTION_DETECTED with entity_count >= 2: someone followed the badge
    holder in. The schema's baseline always emits entity_count=1, so any
    value >= 2 is by construction a tailgating signal in the simulator.

    In a real deployment, the threshold would be calibrated against
    legitimate cases (groups arriving together, etc.). For our
    simulation it's a clean discriminator.

    Contribution: 0.60 (matches the README expected SUSPECT score for
    tailgating). Leaves room for fusion to bump higher when the badge is
    in a sensitive zone or outside hours.
    """
    cond = (
        (df["event_type"] == "MOTION_DETECTED")
        & (df["entity_count"] >= 2.0)
    )
    return np.where(cond, 0.60, 0.0)


def _rule_port_scan(df: pd.DataFrame) -> pd.Series:
    """
    NETWORK_FLOW with very high distinct_dst_ports z-score AND high
    absolute count. The z-score alone could fire on a quiet camera with
    a small bump, so we double-gate.
    """
    cond = (
        (df["event_type"] == "NETWORK_FLOW")
        & (df["distinct_dst_ports_zscore_device"] >= 5.0)
        & (df["distinct_dst_ports"] >= 10.0)
    )
    return np.where(cond, 0.80, 0.0)


def _rule_exfiltration(df: pd.DataFrame) -> pd.Series:
    """
    Sustained high outbound volume to an EXTERNAL destination from a
    device that normally talks internal-only. Two combined signals:
      - bytes_out z-score very high (>= 4)
      - destination is external
    """
    cond = (
        (df["event_type"] == "NETWORK_FLOW")
        & (df["bytes_out_zscore_device"] >= 4.0)
        & (df["dst_is_external"] == 1)
    )
    return np.where(cond, 0.75, 0.0)


def _rule_external_destination(df: pd.DataFrame) -> pd.Series:
    """
    Any external destination from an internal device is mildly
    suspicious by itself (cameras shouldn't talk to external IPs in
    our setup). Lower contribution; mostly here so it lights up
    fusion scoring at step 5.
    """
    cond = (
        (df["event_type"] == "NETWORK_FLOW")
        & (df["dst_is_external"] == 1)
    )
    return np.where(cond, 0.40, 0.0)


def _rule_explicit_network_anomaly(df: pd.DataFrame) -> pd.Series:
    """
    A NETWORK_ANOMALY event from the network agent itself. The agent
    has already pre-classified it; we trust the source-side severity
    hint with a slight discount (fusion will refine).

    The feature DataFrame does not expose severity_hint or anomaly_label
    directly; for now we just flag the event_type with a flat 0.70.
    """
    cond = df["event_type"] == "NETWORK_ANOMALY"
    return np.where(cond, 0.70, 0.0)


# -----------------------------------------------------------------------------
# Registry & engine
# -----------------------------------------------------------------------------

ALL_RULES: list[Rule] = [
    Rule("rule:door_forced", _rule_door_forced),
    Rule("rule:repeated_denied", _rule_repeated_denied_badge),
    Rule("rule:off_hours_restricted", _rule_off_hours_restricted),
    Rule("rule:tailgating", _rule_tailgating),
    Rule("rule:port_scan", _rule_port_scan),
    Rule("rule:exfiltration", _rule_exfiltration),
    Rule("rule:external_dst", _rule_external_destination),
    Rule("rule:network_anomaly", _rule_explicit_network_anomaly),
]


def score_rules(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run every rule on the input feature DataFrame.

    Returns a DataFrame with TWO columns aligned to df.index:
      - score_rules: max contribution across all rules, in [0, 1]
      - rule_hits: pipe-separated string of rule labels that fired
                   (any rule with contribution > 0)
    """
    if len(df) == 0:
        return pd.DataFrame({
            "score_rules": pd.Series(dtype="float32"),
            "rule_hits": pd.Series(dtype="string"),
        })

    # Stack each rule's contribution into a (n_rules, n_rows) matrix.
    contribs = np.zeros((len(ALL_RULES), len(df)), dtype=np.float32)
    fired = np.zeros((len(ALL_RULES), len(df)), dtype=bool)
    for i, rule in enumerate(ALL_RULES):
        c = rule.apply(df).astype(np.float32).to_numpy()
        contribs[i] = c
        fired[i] = c > 0.0

    score = contribs.max(axis=0)

    # Build rule_hits strings. For most rows it's empty.
    labels = np.array([r.label for r in ALL_RULES])
    hits: list[str] = []
    for j in range(len(df)):
        if fired[:, j].any():
            hits.append("|".join(labels[fired[:, j]].tolist()))
        else:
            hits.append("")

    return pd.DataFrame({
        "score_rules": score,
        "rule_hits": pd.Series(hits, dtype="string", index=df.index),
    }, index=df.index)