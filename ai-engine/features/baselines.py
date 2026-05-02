"""
Per-device baselines for network features.

For each camera (identified by device_id), we learn from the normal
dataset:
  - mean and std of bytes_out, bytes_in, distinct_dst_ports

These baselines power the z-score features in network.py, which the
Isolation Forest then uses. Z-score is much more discriminative than
raw bytes because cameras have heterogeneous baselines.

Baselines are persisted to JSON so:
  1. We can train once and reuse on every test scenario.
  2. The extractor is reproducible: re-running scoring on a JSONL with
     a saved baseline file gives bit-identical features.
  3. In production, the baselines.json travels with the model.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from schemas import EventType, NetworkFlowPayload, UnifiedEvent


# Minimum number of observations needed to trust a learned baseline.
# Below this, we fall back to global defaults rather than report an
# under-sampled per-device statistic.
MIN_OBSERVATIONS: int = 30


@dataclass
class DeviceBaseline:
    """Learned statistics for one camera."""

    device_id: str
    n_observations: int = 0

    bytes_out_mean: float = 0.0
    bytes_out_std: float = 1.0
    bytes_in_mean: float = 0.0
    bytes_in_std: float = 1.0
    distinct_dst_ports_mean: float = 0.0
    distinct_dst_ports_std: float = 1.0

    def is_trusted(self) -> bool:
        """True if we have enough samples to use these stats."""
        return self.n_observations >= MIN_OBSERVATIONS


@dataclass
class BaselineCatalog:
    """All per-device baselines, plus a global fallback."""

    per_device: dict[str, DeviceBaseline] = field(default_factory=dict)
    global_baseline: DeviceBaseline = field(
        default_factory=lambda: DeviceBaseline(device_id="__global__")
    )

    # ---- access -------------------------------------------------------------

    def get(self, device_id: str) -> DeviceBaseline:
        """
        Return the device's baseline if trusted, else the global one.
        Never raises -- the caller doesn't need to know about fallbacks.
        """
        b = self.per_device.get(device_id)
        if b is not None and b.is_trusted():
            return b
        return self.global_baseline

    # ---- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "per_device": {
                d: asdict(b) for d, b in self.per_device.items()
            },
            "global": asdict(self.global_baseline),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "BaselineCatalog":
        per_device = {
            d: DeviceBaseline(**v) for d, v in data.get("per_device", {}).items()
        }
        glob_data = data.get("global", {})
        glob = DeviceBaseline(**glob_data) if glob_data else DeviceBaseline(device_id="__global__")
        return cls(per_device=per_device, global_baseline=glob)

    @classmethod
    def read_json(cls, path: Path) -> "BaselineCatalog":
        with path.open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# -----------------------------------------------------------------------------
# Learning
# -----------------------------------------------------------------------------

def learn_baselines(events: Iterable[UnifiedEvent]) -> BaselineCatalog:
    """
    Single-pass learning: streaming mean and std (Welford's algorithm)
    per device + globally. Memory: O(#devices). Time: O(#events).
    """
    # Per-device accumulators: device_id -> dict of running stats.
    # We keep, per metric, the count, mean, and M2 (sum of squared deviations).
    per_dev: dict[str, dict] = {}
    glob: dict = {
        "n": 0,
        "bytes_out_mean": 0.0, "bytes_out_M2": 0.0,
        "bytes_in_mean": 0.0, "bytes_in_M2": 0.0,
        "distinct_dst_ports_mean": 0.0, "distinct_dst_ports_M2": 0.0,
    }

    def _update(acc: dict, key_mean: str, key_M2: str, n: int, value: float) -> None:
        """Welford's online update for one metric."""
        delta = value - acc[key_mean]
        acc[key_mean] += delta / n
        delta2 = value - acc[key_mean]
        acc[key_M2] += delta * delta2

    for ev in events:
        if ev.event_type != EventType.NETWORK_FLOW:
            continue
        payload = ev.payload
        if not isinstance(payload, NetworkFlowPayload):
            continue  # defensive — should not happen given the type check

        bo = float(payload.bytes_out)
        bi = float(payload.bytes_in)
        dp = float(payload.distinct_dst_ports)

        # Per-device
        d = per_dev.setdefault(ev.device_id, {
            "n": 0,
            "bytes_out_mean": 0.0, "bytes_out_M2": 0.0,
            "bytes_in_mean": 0.0, "bytes_in_M2": 0.0,
            "distinct_dst_ports_mean": 0.0, "distinct_dst_ports_M2": 0.0,
        })
        d["n"] += 1
        _update(d, "bytes_out_mean", "bytes_out_M2", d["n"], bo)
        _update(d, "bytes_in_mean", "bytes_in_M2", d["n"], bi)
        _update(d, "distinct_dst_ports_mean", "distinct_dst_ports_M2", d["n"], dp)

        # Global
        glob["n"] += 1
        _update(glob, "bytes_out_mean", "bytes_out_M2", glob["n"], bo)
        _update(glob, "bytes_in_mean", "bytes_in_M2", glob["n"], bi)
        _update(glob, "distinct_dst_ports_mean", "distinct_dst_ports_M2", glob["n"], dp)

    def _finalise(d: dict, device_id: str) -> DeviceBaseline:
        n = d["n"]
        if n < 2:
            # Std requires n>=2; fall back to 1.0 (will give z=0 in that case).
            return DeviceBaseline(
                device_id=device_id, n_observations=n,
                bytes_out_mean=d["bytes_out_mean"], bytes_out_std=1.0,
                bytes_in_mean=d["bytes_in_mean"], bytes_in_std=1.0,
                distinct_dst_ports_mean=d["distinct_dst_ports_mean"],
                distinct_dst_ports_std=1.0,
            )
        # Sample std (divide by n-1).
        return DeviceBaseline(
            device_id=device_id,
            n_observations=n,
            bytes_out_mean=d["bytes_out_mean"],
            bytes_out_std=max(1.0, math.sqrt(d["bytes_out_M2"] / (n - 1))),
            bytes_in_mean=d["bytes_in_mean"],
            bytes_in_std=max(1.0, math.sqrt(d["bytes_in_M2"] / (n - 1))),
            distinct_dst_ports_mean=d["distinct_dst_ports_mean"],
            distinct_dst_ports_std=max(0.5, math.sqrt(d["distinct_dst_ports_M2"] / (n - 1))),
        )

    catalog = BaselineCatalog(
        per_device={did: _finalise(d, did) for did, d in per_dev.items()},
        global_baseline=_finalise(glob, "__global__"),
    )
    return catalog


# -----------------------------------------------------------------------------
# Z-score helper
# -----------------------------------------------------------------------------

def zscore(value: float, mean: float, std: float) -> float:
    """Robust z-score: returns 0 if std is degenerate."""
    if std <= 0 or math.isnan(std):
        return 0.0
    return (value - mean) / std