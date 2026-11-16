"""Cohort handles are deterministic, refinable and persistent."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from courts_analyst.core.cohorts import CohortSpec, CohortStore, find_cases, refine
from courts_analyst.core.db import Database
from courts_analyst.core.errors import (
    DataUnavailableError,
    InvalidCohortError,
    UnknownHandleError,
)


def spec(**kw: object) -> CohortSpec:
    return CohortSpec.model_validate({"fy_from": 2020, "fy_to": 2020, **kw})


def test_same_spec_same_handle() -> None:
    a = spec(courts=["NJ", "FL-N"], nos_groups=["Civil Rights", "Antitrust"])
    b = spec(courts=["FL-N", "NJ", "FL-N"], nos_groups=["Antitrust", "Civil Rights"])
    assert a.handle() == b.handle()
    assert a.handle().startswith("coh_") and len(a.handle()) == 16


def test_equivalent_court_spellings_normalise() -> None:
    all_districts = spec(courts=["US"])
    assert all_districts.handle() == spec().handle()
    circuit = spec(courts=["CIR-11"])
    members = spec(courts=["AL-N", "AL-M", "AL-S", "FL-N", "FL-M", "FL-S", "GA-N",
                           "GA-M", "GA-S"])  # fmt: skip
    assert circuit.handle() == members.handle()


def test_different_specs_differ() -> None:
    assert spec().handle() != spec(basis="terminated").handle()
    assert spec().handle() != spec(exclude_mdl=True).handle()


def test_handle_is_stable_across_releases_of_this_code() -> None:
    # Pinned: a change means old handles (in logs, transcripts) stop resolving.
    assert spec(courts=["FL-N"], origins=["mdl_direct"]).handle() == "coh_1385a2b1481d"


@pytest.mark.parametrize(
    "bad",
    [
        {"fy_from": 2021, "fy_to": 2020},
        {"fy_from": 2010, "fy_to": 2020},
        {"fy_from": 2020, "fy_to": 2020, "courts": ["SDNY"]},
        {"fy_from": 2020, "fy_to": 2020, "nos_codes": ["999"]},
        {"fy_from": 2020, "fy_to": 2020, "origins": ["mdl"]},
        {
            "fy_from": 2020,
            "fy_to": 2020,
            "exclude_mdl": True,
            "origins": ["mdl_direct"],
        },
        {"fy_from": 2020, "fy_to": 2020, "judge": "x"},
    ],
)
def test_invalid_specs(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CohortSpec.model_validate(bad)


def test_find_and_refine_keep_lineage(core_db: Database, store: CohortStore) -> None:
    parent = find_cases(core_db, store, spec(courts=["FL-N"]))
    assert parent.data is not None and parent.data.n > 100
    child = refine(core_db, store, parent.data.handle, {"origins": ["mdl_direct"]})
    assert child.data is not None
    assert child.data.parent == parent.data.handle
    assert child.data.handle == spec(courts=["FL-N"], origins=["mdl_direct"]).handle()
    assert 0 < child.data.n <= parent.data.n
    assert child.data.mdl_direct_share == 1.0
    assert store.get(child.data.handle).parent == parent.data.handle
    with pytest.raises(InvalidCohortError):
        refine(core_db, store, parent.data.handle, {"fy_from": 2030})


def test_unknown_handle_is_a_typed_error(store: CohortStore) -> None:
    with pytest.raises(UnknownHandleError, match="find_cases") as err:
        store.get("coh_000000000000")
    assert err.value.suggested_next == ["find_cases"]


def test_store_persists_across_instances(core_db: Database, tmp_path: Path) -> None:
    path = tmp_path / "state" / "cohorts.duckdb"
    first = CohortStore(path)
    handle = find_cases(core_db, first, spec(courts=["NJ"])).data.handle  # type: ignore[union-attr]
    again = CohortStore(path)
    assert again.get(handle).spec.courts == ["NJ"]


def test_lru_capacity(core_db: Database) -> None:
    small = CohortStore(capacity=2)
    handles = [
        find_cases(core_db, small, spec(courts=[c])).data.handle  # type: ignore[union-attr]
        for c in ("NJ", "DE", "MD")
    ]
    with pytest.raises(UnknownHandleError):
        small.get(handles[0])
    assert small.get(handles[2])


def test_summary_is_a_preview_not_rows(core_db: Database, store: CohortStore) -> None:
    s = find_cases(core_db, store, spec(fy_from=2016, fy_to=2025)).data
    assert s is not None
    assert len(s.top_courts) <= 5 and len(s.top_nos_groups) <= 5
    assert [c.key for c in s.by_fiscal_year] == [str(y) for y in range(2016, 2026)]
    dumped = s.model_dump_json()
    assert "docket" not in dumped and "party" not in dumped.lower()


def test_empty_cohort_warns(core_db: Database, store: CohortStore) -> None:
    r = find_cases(core_db, store, spec(courts=["VT"], nos_codes=["410"]))
    assert r.data is not None and r.data.n == 0
    # Nothing is withheld from an empty cohort (Phase 6): it just has no cases.
    codes = {w.code for w in r.warnings}
    assert "out_of_scope" in codes and "suppressed" not in codes


def test_find_cases_needs_idb(tables_only_db: Database, store: CohortStore) -> None:
    with pytest.raises(DataUnavailableError, match="make data-idb"):
        find_cases(tables_only_db, store, spec())


def test_data_break_warnings_are_scoped(core_db: Database, store: CohortStore) -> None:
    tcpa = find_cases(core_db, store, spec(fy_from=2018, fy_to=2020, nos_codes=["485"]))
    assert any("nos-485" in w.message for w in tcpa.warnings)
    other = find_cases(
        core_db, store, spec(fy_from=2018, fy_to=2020, nos_codes=["830"])
    )
    assert not any("nos-485" in w.message for w in other.warnings)
