"""Decomposition parts always sum to the total (property tests)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.explain import contributions, shift_share

counts = st.dictionaries(
    st.text(alphabet="abcdefghij", min_size=1, max_size=3),
    st.integers(min_value=0, max_value=100_000),
    max_size=30,
)


@given(counts, counts, st.integers(min_value=1, max_value=12))
def test_contributions_sum_exactly_to_the_change(
    before: dict[str, int], after: dict[str, int], limit: int
) -> None:
    rows = contributions(
        {k: float(v) for k, v in before.items()},
        {k: float(v) for k, v in after.items()},
        limit=limit,
    )
    total = sum(after.values()) - sum(before.values())
    assert sum(r.change for r in rows) == pytest.approx(total, abs=1e-6)
    assert len(rows) <= limit + 1
    keys = [r.key for r in rows]
    assert len(keys) == len(set(keys))


@given(counts, counts)
def test_key_contributors_reach_80_percent(
    before: dict[str, int], after: dict[str, int]
) -> None:
    rows = contributions(
        {k: float(v) for k, v in before.items()},
        {k: float(v) for k, v in after.items()},
        limit=100,
    )
    total = sum(after.values()) - sum(before.values())
    key = [r for r in rows if r.key_contributor]
    if total == 0:
        assert not key
        return
    direction = 1 if total > 0 else -1
    assert all(direction * r.change > 0 for r in key)
    if key:
        # Dropping the smallest key contributor leaves less than 80% covered.
        running = sum(r.change for r in key)
        smallest = min(key, key=lambda r: abs(r.change))
        assert direction * (running - smallest.change) < 0.8 * abs(total) + 1e-9


positive = st.floats(min_value=1, max_value=1e7, allow_nan=False)
judges = st.floats(min_value=0.5, max_value=1000, allow_nan=False)


@given(positive, judges, positive, judges)
def test_shift_share_effects_sum_to_the_change(
    f1: float, j1: float, f2: float, j2: float
) -> None:
    filings, judgeships = shift_share(f1, j1, f2, j2)
    assert filings + judgeships == pytest.approx(f2 / j2 - f1 / j1, rel=1e-9, abs=1e-6)


def test_shift_share_pure_cases() -> None:
    assert shift_share(100, 10, 200, 10) == (pytest.approx(10), pytest.approx(0))
    filings, judgeships = shift_share(100, 10, 100, 20)
    assert filings == pytest.approx(0) and judgeships == pytest.approx(-5)


def test_other_row_and_labels() -> None:
    before = {str(i): 10.0 for i in range(15)}
    after = {str(i): 10.0 + i for i in range(15)}
    rows = contributions(before, after, {"14": "Fourteen"}, limit=3)
    assert rows[0].label == "Fourteen" and rows[0].change == 14
    assert rows[-1].key == "__other__" and rows[-1].label == "All other (12)"
    assert sum(r.change for r in rows) == sum(range(15))
