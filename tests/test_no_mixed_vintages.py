"""Never mix vintages: a series across editions is refused unless mixing is
requested, and then every point carries its edition."""

from __future__ import annotations

import pytest

from courts_analyst.core.chain import load_chain
from courts_analyst.core.db import Database
from courts_analyst.core.errors import MixedEditionsError, PolicyViolationError
from courts_analyst.core.explain import explain_change
from courts_analyst.core.guardrails import PolicyContext, apply_policies
from courts_analyst.core.guardrails.vintage import choose_vintage, is_consistent
from courts_analyst.core.official import official_series
from courts_analyst.core.provenance import Provenance
from courts_analyst.core.results import ok

W = "weighted_civil_filings_per_judgeship"


def _chains(db: Database, measure: str, court: str, years: range) -> dict:  # type: ignore[type-arg]
    return {fy: load_chain(db, measure, court, fy) for fy in years}


def test_1990_to_2025_has_no_consistent_series(core_db: Database) -> None:
    with pytest.raises(MixedEditionsError) as exc:
        official_series(core_db, W, "US", 1990, 2025)
    assert "allow_mixed" in " ".join(exc.value.suggested_next)


def test_allow_mixed_labels_every_point(core_db: Database) -> None:
    r = official_series(core_db, W, "US", 1990, 2025, allow_mixed=True)
    assert r.data is not None and not r.data.consistent
    assert all(p.edition for p in r.data.points)
    assert len({p.edition for p in r.data.points}) > 1
    assert any(w.code == "mixed_editions" for w in r.warnings)
    assert any(w.code == "period_mismatch" for w in r.warnings)  # 1990 ends June 30


def test_latest_falls_back_to_one_series(core_db: Database) -> None:
    """FY2016–FY2025 latest values splice pre- and post-revision JFF editions
    (JFF-2020 prints FY2019 as 381, JFF-2023 as 332), so the series falls back
    to Judicial Business as first published, and says so."""
    chains = _chains(core_db, W, "US", range(2016, 2026))
    assert not is_consistent({fy: ch[-1] for fy, ch in chains.items()}, chains)
    r = official_series(core_db, W, "US", 2016, 2025)
    assert r.data is not None and r.data.consistent
    assert {p.edition.split("-")[0] for p in r.data.points} == {"JB"}
    assert next(p.value for p in r.data.points if p.fiscal_year == 2020) == 554
    assert any(w.code == "revised_figure" for w in r.warnings)


def test_explicit_edition(core_db: Database) -> None:
    r = official_series(core_db, W, "US", 2020, 2020, edition="JFF-2025")
    assert r.data is not None and r.data.points[0].value == 322
    with pytest.raises(Exception, match="doesn't print"):
        official_series(core_db, W, "US", 2016, 2025, edition="JFF-2025")


def test_pending_restatement_is_one_series(core_db: Database) -> None:
    """Each JB edition restates the prior year's pending count: the latest
    values are one series; the first-published ones are refused."""
    r = official_series(core_db, "civil_cases_pending", "US", 2016, 2025)
    assert r.data is not None and r.data.consistent
    assert next(p.edition for p in r.data.points if p.fiscal_year == 2017) == "JB-2018"
    with pytest.raises(MixedEditionsError):
        official_series(
            core_db, "civil_cases_pending", "US", 2016, 2025, edition="first_published"
        )


def test_explain_change_uses_one_vintage(core_db: Database) -> None:
    r = explain_change(core_db, "civil_filings_per_judgeship", "US", 1990, 2020)
    assert r.data is not None
    assert r.data.official_from.edition == r.data.official_to.edition
    assert r.data.by_district == []  # JFF has no district rows
    assert {w.code for w in r.warnings} >= {"period_mismatch"}


def test_splice_of_pre_and_post_revision_values_is_inconsistent(
    core_db: Database,
) -> None:
    chains = _chains(core_db, W, "US", range(2019, 2021))
    by_ed = {fy: {r.edition: r for r in ch} for fy, ch in chains.items()}
    # 381 (JFF-2022, pre-revision) next to 322 (JFF-2025): JFF-2022 prints 554.
    assert not is_consistent(
        {2019: by_ed[2019]["JFF-2022"], 2020: by_ed[2020]["JFF-2025"]}, chains
    )
    # Judicial Business with Judicial Business: one series.
    assert is_consistent(
        {2019: by_ed[2019]["JB-2019"], 2020: by_ed[2020]["JB-2020"]}, chains
    )
    # The latest values (332 and 322, both revised series) are consistent.
    v = choose_vintage(chains, "latest")
    assert v.consistent and [r.shown for _, r in sorted(v.points.items())] == [332, 322]


def test_policy_refuses_silent_series_mix() -> None:
    """A result combining JB and JFF values of one measure without saying so is
    a bug, and never leaves the server."""
    from courts_analyst.core.glossary import TermLookup

    provs = [
        Provenance(source="official_table", edition=e, definition="d", table_code="t")
        for e in ("JB-2020", "JFF-2025")
    ]
    r = ok(TermLookup(query="x", found=False), provs)
    with pytest.raises(PolicyViolationError, match="mixed_editions"):
        apply_policies(r, PolicyContext("test"))
