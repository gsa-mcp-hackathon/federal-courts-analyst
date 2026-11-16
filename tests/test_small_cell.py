"""Small-cell rule: boundaries at 9/10/29/30, and suppressed values never
appear anywhere in a result's JSON (Phase 6)."""

from __future__ import annotations

import json
from typing import Any

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
from courts_analyst.core.errors import PolicyViolationError
from courts_analyst.core.guardrails import PolicyContext, apply_policies
from courts_analyst.core.guardrails.policy import SMALL_CELL_SUPPRESS, SMALL_CELL_WARN
from courts_analyst.core.guardrails.small_cells import cell_status, is_small_count
from courts_analyst.core.provenance import Provenance
from courts_analyst.core.results import ok


@pytest.mark.parametrize(
    ("n", "status"),
    [(0, "suppressed"), (9, "suppressed"), (10, "small"), (29, "small"), (30, "ok")],
)
def test_boundaries(n: int, status: str) -> None:
    assert cell_status(n) == status


def test_thresholds_come_from_config() -> None:
    assert (SMALL_CELL_SUPPRESS, SMALL_CELL_WARN) == (10, 30)


@given(st.integers(min_value=0, max_value=10_000))
def test_small_count_is_one_to_nine(n: int) -> None:
    assert is_small_count(n) == (1 <= n <= 9)


def _withheld_dicts(obj: Any) -> list[dict[str, Any]]:
    out = []
    if isinstance(obj, dict):
        if obj.get("status") == "suppressed" or obj.get("suppressed") is True:
            out.append(obj)
        for v in obj.values():
            out += _withheld_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _withheld_dicts(v)
    return out


def _numbers_leak(d: dict[str, Any]) -> list[str]:
    return [
        k
        for k in ("n", "value", "share", "ci_low", "ci_high", "breakdown")
        if d.get(k) is not None
    ]


SMALL_COHORTS = [
    {"courts": ["VT"], "nos_groups": ["Antitrust"]},
    {"courts": ["PR"], "nos_groups": ["Foreclosure"], "fy_from": 2016, "fy_to": 2016},
    {"courts": ["VT"]},
    {"courts": ["WY"], "fy_from": 2016, "fy_to": 2025},
    {"courts": ["CIR-01"]},
    {"courts": ["FL-N"], "origins": ["mdl_direct"]},
]


@pytest.mark.parametrize("filters", SMALL_COHORTS)
@pytest.mark.parametrize(
    ("metric", "group_by"),
    [
        ("count", "court"),
        ("count", "nos_group"),
        ("trend", None),
        ("median_days_to_disposition", "nos_group"),
        ("disposition_rates", "court"),
        ("share_by_nos_group", None),
        ("pro_se_share", "origin"),
    ],
)
def test_suppressed_values_never_in_json(
    core_db: Database,
    store: CohortStore,
    filters: dict[str, Any],
    metric: str,
    group_by: str | None,
) -> None:
    spec = CohortSpec(**{"fy_from": 2019, "fy_to": 2021, **filters})
    summary = find_cases(core_db, store, spec)
    assert summary.data is not None
    for d in _withheld_dicts(summary.model_dump(mode="json")):
        assert not _numbers_leak(d), d
    r = analyze_cohort(core_db, store, spec.handle(), metric, group_by)  # type: ignore[arg-type]
    payload = r.model_dump(mode="json")
    for d in _withheld_dicts(payload):
        assert not _numbers_leak(d), d
    # No shown statistic rests on fewer than 10 cases.
    for g in r.data.results if r.data else []:
        if g.value is not None:
            assert g.n is not None and g.n >= SMALL_CELL_SUPPRESS
    # A count under 10 never appears as a count or in a message.
    for g in r.data.results if r.data else []:
        assert g.n is None or g.n == 0 or g.n >= SMALL_CELL_SUPPRESS
    for w in r.warnings + summary.warnings:
        assert "Only " not in w.message


def test_tiny_cohort_total_is_withheld(core_db: Database, store: CohortStore) -> None:
    spec = CohortSpec(
        courts=["PR"], nos_groups=["Foreclosure"], fy_from=2016, fy_to=2016
    )
    r = find_cases(core_db, store, spec)
    assert r.data is not None
    n = store.get(spec.handle()).n
    assert 0 < n < 10, "fixture should give a tiny cohort"
    assert r.data.n is None and r.data.by_fiscal_year == [] and not r.data.top_courts
    assert r.data.mdl_direct_share is None and r.data.terminated_share is None
    assert any(w.code == "suppressed" and w.severity == "block" for w in r.warnings)
    assert str(n) not in json.dumps([w.message for w in r.warnings])


def test_invariant_catches_a_leaking_cell() -> None:
    """A core bug that leaves a number on a suppressed cell is refused."""
    from courts_analyst.core.cohorts import CohortAnalysis, GroupValue

    bad = CohortAnalysis(
        handle="coh_000000000000",
        metric="count",
        unit="cases",
        group_by=None,
        results=[GroupValue(n=3, value=3.0, status="suppressed")],
        method="x",
    )
    prov = Provenance(source="idb_derived", definition="x")
    with pytest.raises(PolicyViolationError, match="suppressed"):
        apply_policies(ok(bad, [prov]), PolicyContext("test"))
    worse = bad.model_copy(
        update={"results": [GroupValue(n=4, value=12.5, status="ok")]}
    )
    with pytest.raises(PolicyViolationError, match="4 cases"):
        apply_policies(ok(worse, [prov]), PolicyContext("test"))
