"""
Feature DataFrame schema.

Defines the canonical column names, dtypes, and ordering of the feature
DataFrame produced by the extractor. This is the contract between:
  - the extractor (writer)
  - the Isolation Forest training code (reader, step 4)
  - the rules engine (reader, step 4)
  - persistence (parquet / pickle)

Keeping the schema declarative here means we can validate any extracted
DataFrame in one call, and changes to the feature set are visible in one
file rather than scattered across modules.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


# -----------------------------------------------------------------------------
# Identity columns — copied verbatim from the source events for joining
# back to the original data and to the truth.json files.
# -----------------------------------------------------------------------------
IDENTITY_COLUMNS: list[tuple[str, str]] = [
    ("event_id", "string"),
    ("timestamp", "datetime64[ns, UTC]"),
    ("event_type", "string"),
    ("source_layer", "string"),
    ("zone_id", "string"),
    ("device_id", "string"),
    ("user_id", "string"),  # may be null
]


# -----------------------------------------------------------------------------
# Temporal features
# -----------------------------------------------------------------------------
TEMPORAL_COLUMNS: list[tuple[str, str]] = [
    # Hour-of-day encoded cyclically so that 23:59 and 00:00 are close.
    ("hour_sin", "float32"),
    ("hour_cos", "float32"),
    # Day-of-week 0=Mon, 6=Sun.
    ("day_of_week", "int8"),
    ("is_weekend", "int8"),
    # Whether the event happened within the user's typical working window.
    # (For unattributed events: 0.) Soft signal: 0 if outside.
    ("is_within_typical_hours", "int8"),
    # Signed distance in MINUTES from typical_arrival/departure midpoint.
    # Negative = early/before, positive = late/after. NaN when no user.
    ("minutes_off_typical_midshift", "float32"),
]


# -----------------------------------------------------------------------------
# Spatial features
# -----------------------------------------------------------------------------
SPATIAL_COLUMNS: list[tuple[str, str]] = [
    # Zone sensitivity 0=PUBLIC, 1=STANDARD, 2=RESTRICTED, 3=CRITICAL
    ("zone_sensitivity_lvl", "int8"),
    # Whether this zone is in the user's typical_zones list.
    # (Unattributed events: -1, distinguishable from the boolean values.)
    ("is_typical_zone_for_user", "int8"),
    # Number of moving entities reported by a motion sensor. NaN for any
    # event type other than MOTION_DETECTED. Float32 because of NaN.
    # entity_count >= 2 paired with a single badge in the same window
    # is the tailgating signal.
    ("entity_count", "float32"),
]


# -----------------------------------------------------------------------------
# Frequency features (sliding windows over the recent past)
# -----------------------------------------------------------------------------
FREQUENCY_COLUMNS: list[tuple[str, str]] = [
    # Number of events for this user in the last 1h / 24h.
    ("events_user_last_1h", "int32"),
    ("events_user_last_24h", "int32"),
    # Number of events in this zone in the last 5min / 1h.
    ("events_zone_last_5min", "int32"),
    ("events_zone_last_1h", "int32"),
    # Recent denied-badge count for this user / zone (5 min window).
    ("denied_badges_user_last_5min", "int32"),
    ("denied_badges_zone_last_5min", "int32"),
]


# -----------------------------------------------------------------------------
# Network features (only meaningful for NETWORK_FLOW events; NaN/0 otherwise)
# -----------------------------------------------------------------------------
NETWORK_COLUMNS: list[tuple[str, str]] = [
    # Raw values from the payload (already in the event but kept here so the
    # IF doesn't have to re-parse the payload).
    ("bytes_out", "float32"),
    ("bytes_in", "float32"),
    ("distinct_dst_ports", "float32"),
    # Z-scores against the per-device baseline (learned from train_normal).
    # Higher = unusual outbound. NaN if device has no learned baseline.
    ("bytes_out_zscore_device", "float32"),
    ("bytes_in_zscore_device", "float32"),
    ("distinct_dst_ports_zscore_device", "float32"),
    # External destination flag: 1 if dst_ip is outside 10.0.0.0/8, 0 otherwise.
    ("dst_is_external", "int8"),
]


# -----------------------------------------------------------------------------
# Combined ordered schema
# -----------------------------------------------------------------------------
ALL_COLUMNS: list[tuple[str, str]] = (
    IDENTITY_COLUMNS
    + TEMPORAL_COLUMNS
    + SPATIAL_COLUMNS
    + FREQUENCY_COLUMNS
    + NETWORK_COLUMNS
)

COLUMN_NAMES: list[str] = [name for name, _ in ALL_COLUMNS]
COLUMN_DTYPES: dict[str, str] = dict(ALL_COLUMNS)


def make_empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema and dtypes."""
    df = pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in ALL_COLUMNS})
    return df[COLUMN_NAMES]


def coerce_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce an arbitrary DataFrame to the canonical schema.

    - Reorders columns to COLUMN_NAMES order.
    - Casts each column to its declared dtype.
    - Raises KeyError if any required column is missing.
    """
    missing = [c for c in COLUMN_NAMES if c not in df.columns]
    if missing:
        raise KeyError(f"Missing feature columns: {missing}")

    out = df[COLUMN_NAMES].copy()
    for name, dtype in ALL_COLUMNS:
        # Special handling for nullable / timezone-aware types.
        if dtype == "datetime64[ns, UTC]":
            out[name] = pd.to_datetime(out[name], utc=True)
        else:
            try:
                out[name] = out[name].astype(dtype)
            except (ValueError, TypeError):
                # int columns can't hold NaN; skip cast and let downstream
                # code handle it.
                pass
    return out


# -----------------------------------------------------------------------------
# Feature groups (for selective use in models)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureGroups:
    """Convenience access to named subsets of feature columns."""

    @property
    def identity(self) -> list[str]:
        return [name for name, _ in IDENTITY_COLUMNS]

    @property
    def temporal(self) -> list[str]:
        return [name for name, _ in TEMPORAL_COLUMNS]

    @property
    def spatial(self) -> list[str]:
        return [name for name, _ in SPATIAL_COLUMNS]

    @property
    def frequency(self) -> list[str]:
        return [name for name, _ in FREQUENCY_COLUMNS]

    @property
    def network(self) -> list[str]:
        return [name for name, _ in NETWORK_COLUMNS]

    @property
    def numeric_for_if(self) -> list[str]:
        """Numeric columns suitable as Isolation Forest input."""
        return self.temporal + self.spatial + self.frequency + self.network


GROUPS = FeatureGroups()