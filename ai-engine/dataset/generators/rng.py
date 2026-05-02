"""
Centralised random-number generation.

Why a wrapper instead of using `random` and `numpy.random` directly?

  1. Reproducibility: a single seed at the top of the pipeline determines
     every event in the dataset. We want the same seed to give bit-identical
     output across machines (Ilyes' Mac, your Mac, CI), regardless of import
     order.

  2. Hierarchical seeding: each user / day / scenario gets its own derived
     seed, so re-running ONE user's day doesn't shift the random stream for
     all the others. This is essential when debugging.

  3. No global state: every generator receives a `Rng` instance explicitly.
     This makes accidental nondeterminism impossible (no hidden module-level
     `random.seed()` calls).

The implementation uses NumPy's modern `Generator` API which is
self-contained and fully deterministic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass
class Rng:
    """
    A reproducible random number generator with hierarchical sub-seeding.

    Use:
        master = Rng(seed=42)
        alice_rng = master.derive("user", "u001")
        alice_day1 = alice_rng.derive("day", "2026-04-01")
    """

    seed: int

    def __post_init__(self) -> None:
        # NumPy's PCG64 generator: fast, statistically sound, fully seedable.
        self._gen = np.random.default_rng(self.seed)

    # ---- Sub-seeding ---------------------------------------------------------

    def derive(self, *labels: str) -> "Rng":
        """
        Derive a child RNG whose seed is a deterministic function of this
        RNG's seed and the labels.

        Two RNGs derived with the same labels from the same parent always
        produce the same stream. Different labels give independent streams.
        """
        # Hash (parent seed + labels) into a stable 64-bit integer.
        h = hashlib.blake2b(digest_size=8)
        h.update(self.seed.to_bytes(8, "big", signed=False))
        for label in labels:
            h.update(b"\x00")  # separator avoids "ab" + "c" colliding with "a" + "bc"
            h.update(label.encode("utf-8"))
        derived_seed = int.from_bytes(h.digest(), "big")
        # Cap at int64 to stay within NumPy's accepted seed range.
        derived_seed &= (1 << 63) - 1
        return Rng(seed=derived_seed)

    # ---- Distributions used by generators ------------------------------------

    def normal(self, mean: float, std: float) -> float:
        """One sample from a normal (gaussian) distribution."""
        return float(self._gen.normal(mean, std))

    def uniform(self, low: float, high: float) -> float:
        """One sample from a uniform distribution on [low, high)."""
        return float(self._gen.uniform(low, high))

    def lognormal(self, mean: float, sigma: float) -> float:
        """One sample from a lognormal distribution (mean and sigma in log-space)."""
        return float(self._gen.lognormal(mean, sigma))

    def poisson(self, lam: float) -> int:
        """One sample from a Poisson distribution (used for counts of events)."""
        return int(self._gen.poisson(lam))

    def randint(self, low: int, high: int) -> int:
        """One integer uniformly in [low, high) (high-exclusive, like numpy)."""
        return int(self._gen.integers(low, high))

    def choice(self, seq):
        """Uniform choice from a non-empty sequence."""
        if len(seq) == 0:
            raise ValueError("choice() called on empty sequence")
        idx = int(self._gen.integers(0, len(seq)))
        return seq[idx]

    def weighted_choice(self, seq, weights):
        """Choice from `seq` with the given non-negative weights (need not sum to 1)."""
        if len(seq) == 0:
            raise ValueError("weighted_choice() called on empty sequence")
        if len(seq) != len(weights):
            raise ValueError("seq and weights must have the same length")
        w = np.asarray(weights, dtype=float)
        total = w.sum()
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        probs = w / total
        idx = int(self._gen.choice(len(seq), p=probs))
        return seq[idx]

    def bernoulli(self, p: float) -> bool:
        """True with probability p."""
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"bernoulli probability must be in [0,1], got {p}")
        return bool(self._gen.random() < p)
