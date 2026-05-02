"""
Network features.

Computes z-scores and external-destination flags for NETWORK_FLOW events.
For events that are NOT network flows, returns NaN/0 -- the schema marks
these as float so missing values are representable.
"""

from __future__ import annotations

import math

from schemas import EventType, NetworkFlowPayload, UnifiedEvent

from .baselines import BaselineCatalog, zscore


# Networks considered "internal" for the dst_is_external flag.
# 10.0.0.0/8 is the simulated internal range used by topology.
_INTERNAL_PREFIXES = ("10.",)


def _is_internal(ip: str) -> bool:
    return any(ip.startswith(p) for p in _INTERNAL_PREFIXES)


def network_features(
    event: UnifiedEvent, catalog: BaselineCatalog
) -> dict:
    """
    Returns a dict with the network-feature columns. Non-network events
    get NaN for the float fields and 0 for the integer flag.
    """
    if event.event_type != EventType.NETWORK_FLOW:
        return {
            "bytes_out": float("nan"),
            "bytes_in": float("nan"),
            "distinct_dst_ports": float("nan"),
            "bytes_out_zscore_device": float("nan"),
            "bytes_in_zscore_device": float("nan"),
            "distinct_dst_ports_zscore_device": float("nan"),
            "dst_is_external": 0,
        }

    payload = event.payload
    assert isinstance(payload, NetworkFlowPayload)
    bo = float(payload.bytes_out)
    bi = float(payload.bytes_in)
    dp = float(payload.distinct_dst_ports)

    baseline = catalog.get(event.device_id)

    return {
        "bytes_out": bo,
        "bytes_in": bi,
        "distinct_dst_ports": dp,
        "bytes_out_zscore_device": zscore(
            bo, baseline.bytes_out_mean, baseline.bytes_out_std
        ),
        "bytes_in_zscore_device": zscore(
            bi, baseline.bytes_in_mean, baseline.bytes_in_std
        ),
        "distinct_dst_ports_zscore_device": zscore(
            dp,
            baseline.distinct_dst_ports_mean,
            baseline.distinct_dst_ports_std,
        ),
        "dst_is_external": 0 if _is_internal(payload.dst_ip) else 1,
    }