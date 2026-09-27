"""Small cells and complementary suppression.

Two rules (thresholds in ``core/data/guardrails.yaml``):

* **Small cells.** A statistic (median, rate, share, interval) computed from
  fewer than 10 cases is withheld, and 10–29 cases carry a caution. A *count*
  of 1–9 cases in an IDB breakdown is shown as suppressed ("fewer than 10").
* **Complementary suppression.** When a breakdown's cells add up to a total
  the result also shows, withholding one small cell isn't enough: total minus
  the visible cells gives it back. :func:`protect` withholds further cells
  (the smallest visible ones) until no withheld cell can be worked out.

The attacker model, stated so the property tests can check it exactly: the
reader knows the total, every visible cell, that each withheld cell is at
least 1, that cells withheld for being small are at most 9, and that cells
withheld to protect them are at least 10 and no larger than the smallest
visible cell. A withheld cell is *recovered* when those facts leave it one
possible value. Counts are integers and the constraints are bounds plus one
sum, so each cell's feasible values form an interval (:func:`feasible`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from courts_analyst.core.guardrails.policy import SMALL_CELL_SUPPRESS, SMALL_CELL_WARN

CellStatus = Literal["ok", "small", "suppressed"]


def cell_status(n: int) -> CellStatus:
    """``suppressed`` below 10 cases, ``small`` below 30, else ``ok``."""
    if n < SMALL_CELL_SUPPRESS:
        return "suppressed"
    if n < SMALL_CELL_WARN:
        return "small"
    return "ok"


def is_small_count(n: int) -> bool:
    """A count that is reported as suppressed: 1–9 (zero is not disclosive)."""
    return 0 < n < SMALL_CELL_SUPPRESS


@dataclass(frozen=True)
class Protection:
    """Which cells of a breakdown to withhold."""

    primary: frozenset[int]
    """Withheld for being small."""
    complementary: frozenset[int]
    """Withheld so the primary cells can't be recovered."""
    total_suppressed: bool = False
    """Even withholding every cell isn't enough: the total must go too."""

    @property
    def withheld(self) -> frozenset[int]:
        return self.primary | self.complementary


def bounds(
    values: Sequence[int], primary: set[int] | frozenset[int], withheld: set[int]
) -> dict[int, tuple[int, float]]:
    """What the attacker model knows about each withheld cell."""
    visible = [v for i, v in enumerate(values) if i not in withheld]
    cap = min(visible) if visible else math.inf
    out: dict[int, tuple[int, float]] = {}
    for i in withheld:
        if i in primary:
            out[i] = (1, SMALL_CELL_SUPPRESS - 1)
        else:
            out[i] = (SMALL_CELL_SUPPRESS, cap)
    return out


def feasible(
    known_sum: int, box: dict[int, tuple[int, float]]
) -> dict[int, tuple[float, float]]:
    """Each withheld cell's feasible interval given the withheld cells' sum."""
    lo_total = sum(lo for lo, _ in box.values())
    hi_total = sum(hi for _, hi in box.values())
    out: dict[int, tuple[float, float]] = {}
    for i, (lo, hi) in box.items():
        others_lo = lo_total - lo
        others_hi = hi_total - hi
        out[i] = (max(lo, known_sum - others_hi), min(hi, known_sum - others_lo))
    return out


def recovered(
    values: Sequence[int], primary: set[int] | frozenset[int], withheld: set[int]
) -> set[int]:
    """Withheld cells the attacker model pins to a single value."""
    if not withheld:
        return set()
    box = bounds(values, primary, withheld)
    s = sum(values[i] for i in withheld)
    return {i for i, (lo, hi) in feasible(s, box).items() if lo >= hi}


def protect(values: Sequence[int], total_shown: bool = True) -> Protection:
    """Cells to withhold in a breakdown of counts ``values``.

    Cells of 1–9 are withheld. If the breakdown's total is shown, the smallest
    visible cells are withheld too until no withheld cell can be recovered;
    if that needs every cell, ``total_suppressed`` says the total must go.
    """
    primary = {i for i, v in enumerate(values) if is_small_count(v)}
    if not total_shown or not primary:
        return Protection(frozenset(primary), frozenset())
    withheld = set(primary)
    order = sorted(
        (i for i in range(len(values)) if i not in withheld and values[i] > 0),
        key=lambda i: (values[i], i),
    )
    while recovered(values, primary, withheld):
        if not order:
            return Protection(
                frozenset(primary), frozenset(withheld - primary), total_suppressed=True
            )
        withheld.add(order.pop(0))
    return Protection(frozenset(primary), frozenset(withheld - primary))


def protect_pairs(
    rows: Sequence[tuple[float, float]], always_hidden: set[int] | None = None
) -> set[int]:
    """Rows of a two-year breakdown to fold into one "all other" row.

    A row whose counts are under 10 in *both* years is folded (a row going
    from 3 to 500 is about 500 cases and stays). The folded rows' sums are
    shown, so folding continues with the smallest remaining rows until no
    folded row's count in either year can be recovered. ``always_hidden``
    rows (beyond the display limit) are folded regardless.
    """
    hidden = set(always_hidden or ())
    primary = {
        i
        for i, (a, b) in enumerate(rows)
        if max(a, b) > 0 and max(a, b) < SMALL_CELL_SUPPRESS
    }
    hidden |= primary
    if not primary:
        return hidden
    order = sorted(
        (i for i in range(len(rows)) if i not in hidden),
        key=lambda i: (max(rows[i]), i),
    )

    def exposed() -> bool:
        for k in (0, 1):
            vals = [int(r[k]) for r in rows]
            box: dict[int, tuple[int, float]] = {
                i: (0, SMALL_CELL_SUPPRESS - 1) if i in primary else (0, math.inf)
                for i in hidden
            }
            s = sum(vals[i] for i in hidden)
            for i, (lo, hi) in feasible(s, box).items():
                # A zero isn't disclosive: only a pinned positive count is.
                if i in primary and lo >= hi and vals[i] > 0:
                    return True
        return False

    while exposed() and order:
        hidden.add(order.pop(0))
    return hidden
