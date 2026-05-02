"""
ai-engine features package.

Public API: import what you need directly from this package.
"""

from .baselines import BaselineCatalog, DeviceBaseline, learn_baselines, zscore
from .extractor import FeatureExtractor
from .io import read_events_jsonl
from .schema import (
    ALL_COLUMNS,
    COLUMN_DTYPES,
    COLUMN_NAMES,
    GROUPS,
    coerce_dataframe,
    make_empty_dataframe,
)

__all__ = [
    "FeatureExtractor",
    "BaselineCatalog",
    "DeviceBaseline",
    "learn_baselines",
    "zscore",
    "read_events_jsonl",
    "ALL_COLUMNS",
    "COLUMN_DTYPES",
    "COLUMN_NAMES",
    "GROUPS",
    "coerce_dataframe",
    "make_empty_dataframe",
]