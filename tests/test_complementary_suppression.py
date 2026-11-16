"""Complementary suppression: no withheld cell can be recovered from the
total and the visible cells.

The check here is independent of the algorithm's own interval arithmetic: a
brute-force attacker enumerates every assignment of the withheld cells that
fits what it knows (the attacker model in core/guardrails/small_cells.py) and
asserts each withheld cell has more than one possible value.
"""

from __future__ import annotations

import itertools
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from courts_analyst.core.cohorts import (
    CohortSpec,
    CohortStore,
    analyze_cohort,
    find_cases,
)
from courts_analyst.core.db import Database
from courts_analyst.core.explain import contributions
from courts_analyst.core.guardrails.small_cells import protect, protect_pairs

LIMIT = 60  # enumeration cap for a "no larger than the smallest visible" bound


def _possible_values(
    values: list[int], primary: set[int], withheld: set[int]
) -> dict[int, set[int]]:
    visible = [v for i, v in enumerate(values) if i not in withheld]
    cap = min(visible) if visible else LIMIT
    ranges = {
        i: range(1, 10) if i in primary else range(10, min(cap, LIMIT) + 1)
        for i in withheld
    }
    target = sum(values[i] for i in withheld)
    order = sorted(withheld)
    seen: dict[int, set[int]] = {i: set() for i in order}
    for combo in itertools.product(*(ranges[i] for i in order)):
        if sum(combo) == target:
            for i, v in zip(order, combo, strict=True):
                seen[i].add(v)
    return seen


breakdowns = st.lists(
    st.one_of(st.integers(1, 9), st.integers(10, 40)), min_size=1, max_size=5
)


@settings(max_examples=400, deadline=None)
@given(breakdowns)
def test_no_withheld_cell_is_recoverable(values: list[int]) -> None:
    guard = protect(values)
    primary = set(guard.primary)
    assert primary == {i for i, v in enumerate(values) if v < 10}
    if guard.total_suppressed:
        return  # the total isn't shown either, so nothing constrains the cells
    for i, possible in _possible_values(values, primary, set(guard.withheld)).items():
        assert values[i] in possible
        assert len(possible) > 1, (values, sorted(guard.withheld), i, possible)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(10, 10_000), min_size=1, max_size=8))
def test_nothing_withheld_without_small_cells(values: list[int]) -> None:
    assert not protect(values).withheld


@pytest.mark.parametrize(
    ("values", "withheld"),
    [
        ([3, 500], {0, 1}),  # one small cell: its complement goes too
        ([3, 4, 500], {0, 1}),  # two small cells hide each other
        ([1, 1, 500, 800], {0, 1, 2}),  # 1+1=2 pins both: add the next smallest
        ([5], {0}),
    ],
)
def test_examples(values: list[int], withheld: set[int]) -> None:
    assert set(protect(values).withheld) == withheld


def test_total_not_shown_needs_no_complement() -> None:
    assert set(protect([3, 500], total_shown=False).withheld) == {0}


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.one_of(st.integers(0, 9), st.integers(10, 300)),
            st.one_of(st.integers(0, 9), st.integers(10, 300)),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_folded_rows_not_recoverable(rows: list[tuple[int, int]]) -> None:
    """explain_change's "All other" row can't give a small row back."""
    hidden = protect_pairs(rows)
    small = {i for i, (a, b) in enumerate(rows) if 0 < max(a, b) < 10}
    assert small <= hidden
    visible = [i for i in range(len(rows)) if i not in hidden]
    if not visible:
        return
    for k in (0, 1):
        target = sum(rows[i][k] for i in hidden)
        # Other hidden rows could be any size (0..inf); small ones 0..9.
        for i in small:
            if rows[i][k] == 0:
                continue
            lo = max(
                0,
                target
                - sum(math.inf if j not in small else 9 for j in hidden if j != i),
            )
            hi = min(9, target)
            assert lo < hi, (rows, sorted(hidden), i, k)


def test_contributions_still_add_up_after_folding() -> None:
    before = {"a": 500.0, "b": 3.0, "c": 2.0, "d": 40.0}
    after = {"a": 700.0, "b": 1.0, "c": 5.0, "d": 35.0}
    rows = contributions(before, after, small_cells=True)
    assert sum(r.change for r in rows) == pytest.approx(
        sum(after.values()) - sum(before.values())
    )
    assert {r.key for r in rows} >= {"a", "__other__"}
    assert "b" not in {r.key for r in rows} and "c" not in {r.key for r in rows}


def test_fiscal_year_preview_protected(core_db: Database, store: CohortStore) -> None:
    """In real previews, withheld years can't be recovered from n."""
    for courts in (["VT"], ["WY"], ["ME"], ["CIR-01"], ["US"]):
        spec = CohortSpec(
            courts=courts,
            fy_from=2016,
            fy_to=2025,
            nos_groups=["Other Contract Actions"],
        )
        s = find_cases(core_db, store, spec).data
        assert s is not None
        if s.n is None:
            continue
        withheld = [c for c in s.by_fiscal_year if c.suppressed]
        assert len(withheld) != 1, courts
        shown = sum(c.n or 0 for c in s.by_fiscal_year)
        if withheld:
            assert s.n - shown >= 2  # at least two cells of at least 1 each


def test_group_counts_protected(core_db: Database, store: CohortStore) -> None:
    spec = CohortSpec(courts=["CIR-02"], fy_from=2020, fy_to=2020)
    find_cases(core_db, store, spec)
    r = analyze_cohort(core_db, store, spec.handle(), "count", "nos_group")
    assert r.data is not None
    withheld = [g for g in r.data.results if g.status == "suppressed"]
    assert len(withheld) != 1
    assert all(g.n is None and g.value is None for g in withheld)
