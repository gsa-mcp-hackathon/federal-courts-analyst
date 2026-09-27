"""Small, dependency-free statistics: Wilson intervals for rates, a
distribution-free interval for medians, and the small-cell rule.

The median interval uses order statistics (the binomial method), not a
bootstrap: it is exact in coverage for continuous data, needs no random
numbers (so results are reproducible across runs), and costs two quantile
lookups instead of thousands of resamples over hundreds of thousands of cases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

Z95: Final = 1.959963984540054

SMALL_CELL_WARN: Final = 30
"""Below this many cases a result is reported with a caution (plan decision 3)."""
SMALL_CELL_SUPPRESS: Final = 10
"""Below this many cases a value is withheld (plan decision 3; Phase 6 reviews)."""

CellStatus = Literal["ok", "small", "suppressed"]


def cell_status(n: int) -> CellStatus:
    if n < SMALL_CELL_SUPPRESS:
        return "suppressed"
    if n < SMALL_CELL_WARN:
        return "small"
    return "ok"


@dataclass(frozen=True, slots=True)
class Interval:
    low: float
    high: float


def wilson(k: int, n: int, z: float = Z95) -> Interval:
    """Wilson score interval for a proportion k/n."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return Interval(low, high)


def _binom_cdf(k: int, n: int) -> float:
    """P(X <= k) for X ~ Binomial(n, 1/2), exact for the small n it's used at."""
    return sum(math.comb(n, i) for i in range(k + 1)) / (1 << n)


def median_ci_ranks(n: int, z: float = Z95) -> tuple[int, int] | None:
    """1-based ranks (j, k) of the order statistics bounding a 95% CI for the
    median of n values, or None when n is too small for one (n < 6).

    Exact binomial ranks for n ≤ 200, the normal approximation above that.
    """
    if n < 6:
        return None
    if n <= 200:
        # Largest j with P(X < j) <= 2.5%, symmetric k = n + 1 - j.
        j = 0
        while _binom_cdf(j, n) <= 0.025:
            j += 1
        j = max(j, 1)
        return j, n + 1 - j
    half = z * math.sqrt(n) / 2
    j = max(1, math.floor(n / 2 - half))
    k = min(n, math.ceil(n / 2 + half) + 1)
    return j, k
