"""Statistics: Wilson and median intervals on known data; small-cell rules."""

from __future__ import annotations

import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.cohorts import (
    CohortSpec,
    CohortStore,
    analyze_cohort,
    find_cases,
)
from courts_analyst.core.db import Database
from courts_analyst.core.stats import cell_status, median_ci_ranks, wilson


def test_wilson_known_values() -> None:
    # Reference values (Wilson 1927; e.g. Newcombe 1998, table I).
    ci = wilson(81, 263)
    assert ci.low == pytest.approx(0.2553, abs=1e-4)
    assert ci.high == pytest.approx(0.3662, abs=1e-4)
    zero = wilson(0, 10)
    assert zero.low == 0 and zero.high == pytest.approx(0.2775, abs=1e-4)
    full = wilson(10, 10)
    assert full.high == 1 and full.low == pytest.approx(0.7225, abs=1e-4)
    with pytest.raises(ValueError):
        wilson(1, 0)
    with pytest.raises(ValueError):
        wilson(5, 3)


@given(st.integers(1, 5000), st.data())
def test_wilson_contains_the_estimate(n: int, data: st.DataObject) -> None:
    k = data.draw(st.integers(0, n))
    ci = wilson(k, n)
    assert 0 <= ci.low <= k / n <= ci.high <= 1


def test_median_ranks_exact_small_n() -> None:
    assert median_ci_ranks(5) is None
    assert median_ci_ranks(6) == (1, 6)
    assert median_ci_ranks(10) == (2, 9)  # coverage 97.9%
    assert median_ci_ranks(20) == (6, 15)  # coverage 95.9%
    assert median_ci_ranks(100) == (40, 61)


@given(st.integers(6, 3000))
def test_median_ranks_are_ordered(n: int) -> None:
    ranks = median_ci_ranks(n)
    assert ranks is not None
    j, k = ranks
    assert 1 <= j <= (n + 1) / 2 <= k <= n


def test_median_ci_coverage_by_simulation() -> None:
    """The order-statistic interval covers the true median ~95% of the time."""
    rng = random.Random(7)
    n, hits, trials = 101, 0, 2000
    for _ in range(trials):
        xs = sorted(rng.expovariate(1.0) for _ in range(n))
        ranks = median_ci_ranks(n)
        assert ranks
        j, k = ranks
        hits += xs[j - 1] <= math.log(2) <= xs[k - 1]
    assert 0.93 <= hits / trials <= 0.98


@pytest.mark.parametrize(
    ("n", "status"),
    [
        (0, "suppressed"),
        (9, "suppressed"),
        (10, "small"),
        (29, "small"),
        (30, "ok"),
        (1000, "ok"),
    ],
)
def test_small_cell_boundaries(n: int, status: str) -> None:
    assert cell_status(n) == status


def _cohort(db: Database, store: CohortStore, **kw: object) -> str:
    s = CohortSpec.model_validate({"fy_from": 2016, "fy_to": 2025, **kw})
    r = find_cases(db, store, s)
    assert r.data is not None
    return r.data.handle


def test_median_on_fixture(core_db: Database, store: CohortStore) -> None:
    h = _cohort(core_db, store)
    r = analyze_cohort(core_db, store, h, "median_days_to_disposition")
    g = r.data.results[0]  # type: ignore[union-attr]
    assert g.n > 1000 and g.value is not None
    assert g.ci_low is not None and g.ci_high is not None
    assert g.ci_low <= g.value <= g.ci_high
    assert r.data.unit == "days"  # type: ignore[union-attr]
    assert "order statistics" in r.data.method  # type: ignore[union-attr]


def test_rates_have_breakdown_and_ci(core_db: Database, store: CohortStore) -> None:
    h = _cohort(core_db, store, basis="terminated")
    g = analyze_cohort(core_db, store, h, "disposition_rates").data.results[0]  # type: ignore[union-attr]
    assert g.breakdown and sum(b.n for b in g.breakdown) == g.n
    assert sum(b.share for b in g.breakdown) == pytest.approx(1)  # type: ignore[misc]
    assert g.ci_low is not None and g.ci_low <= g.value <= g.ci_high  # type: ignore[operator]


def test_group_by_and_suppression(core_db: Database, store: CohortStore) -> None:
    h = _cohort(core_db, store)
    r = analyze_cohort(
        core_db, store, h, "median_days_to_disposition", group_by="court"
    )
    data = r.data
    assert data is not None
    assert len(data.results) == 25 and data.groups_omitted > 0
    assert any(w.code == "truncated" for w in r.warnings)
    few = _cohort(core_db, store, courts=["VT"])
    r = analyze_cohort(
        core_db, store, few, "median_days_to_disposition", group_by="nos_group"
    )
    groups = r.data.results  # type: ignore[union-attr]
    # Small groups are withheld whole: no value and no n (Phase 6).
    tiny = [g for g in groups if g.status == "suppressed"]
    assert tiny and all(g.value is None and g.n is None for g in tiny)
    assert all(g.value is not None and g.n >= 10 for g in groups if g.n is not None)
    assert any(w.code == "suppressed" for w in r.warnings)


@pytest.mark.parametrize(
    "metric",
    [
        "count",
        "trend",
        "judgment_for_rates",
        "share_by_nos_group",
        "pro_se_share",
        "still_pending_share",
    ],
)
def test_every_metric_runs(core_db: Database, store: CohortStore, metric: str) -> None:
    h = _cohort(core_db, store, courts=["FL-N"])
    r = analyze_cohort(core_db, store, h, metric)  # type: ignore[arg-type]
    assert r.data is not None and r.data.results
    assert r.provenance[0].source == "idb_derived"
    if metric == "trend":
        assert r.data.group_by == "fiscal_year"
        keys = [g.group for g in r.data.results]
        assert keys == sorted(keys)  # type: ignore[type-var]


def test_small_cohort_is_suppressed(core_db: Database, store: CohortStore) -> None:
    h = _cohort(core_db, store, courts=["VT"], nos_groups=["Antitrust"])
    r = analyze_cohort(core_db, store, h, "median_days_to_disposition")
    g = r.data.results[0]  # type: ignore[union-attr]
    assert g.value is None and g.status == "suppressed"
    assert any(w.code == "suppressed" and w.severity == "block" for w in r.warnings)
