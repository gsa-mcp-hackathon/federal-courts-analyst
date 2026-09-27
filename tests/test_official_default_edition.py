"""Official figures: default edition (ADR 0004), revisions, errors, and
court comparisons that never mix editions."""

from __future__ import annotations

import pytest

from courts_analyst.core.db import Database
from courts_analyst.core.errors import (
    NotPublishedError,
    OutOfScopeError,
    UnknownCourtError,
    UnknownEditionError,
    UnknownMeasureError,
)
from courts_analyst.core.official import compare_courts, get_official_figure

W = "weighted_civil_filings_per_judgeship"


def test_fy2020_weighted_defaults_to_latest_with_first_published(
    core_db: Database,
) -> None:
    r = get_official_figure(core_db, W, "US", 2020)
    f = r.data
    assert f is not None
    assert f.value == 322 and f.edition == "JFF-2025"
    assert f.revision_status == "revised"
    assert (f.first_published.value, f.first_published.edition) == (554, "JB-2020")
    assert {e.edition for e in f.editions if e.value == 322} == {
        "JFF-2023",
        "JFF-2024",
        "JFF-2025",
    }
    prov = r.provenance[0]
    assert prov.source == "official_table" and prov.edition == "JFF-2025"
    assert prov.first_published == f.first_published
    assert [x.edition for x in prov.later_revisions] == ["JFF-2023"]
    assert prov.url and prov.cell_ref and prov.definition
    assert any(w.code == "revised_figure" and "554" in w.message for w in r.warnings)


@pytest.mark.parametrize(
    ("edition", "value"),
    [("JB-2020", 554), ("first_published", 554), ("JFF-2023", 322), ("latest", 322)],
)
def test_explicit_editions(core_db: Database, edition: str, value: float) -> None:
    r = get_official_figure(core_db, W, "US", 2020, edition)
    assert r.data is not None and r.data.value == value


def test_old_edition_warns_about_current_figure(core_db: Database) -> None:
    r = get_official_figure(core_db, W, "US", 2020, "JB-2020")
    assert any("current official figure is 322" in w.message for w in r.warnings)


def test_judgeships_673_vs_674(core_db: Database) -> None:
    r = get_official_figure(core_db, "authorized_judgeships", "US", 2020)
    assert r.data is not None
    assert (r.data.value, r.data.first_published.value) == (674, 673)


def test_unrevised_and_single_edition_status(core_db: Database) -> None:
    single = get_official_figure(core_db, W, "FL-N", 2020).data
    assert single is not None and single.revision_status == "only_edition"
    same = get_official_figure(
        core_db, "civil_median_months_to_disposition", "US", 2020
    )
    assert same.data is not None and same.data.revision_status == "original"
    assert not any(w.code == "revised_figure" for w in same.warnings)


def test_statistical_year_is_flagged(core_db: Database) -> None:
    r = get_official_figure(core_db, "civil_filings_per_judgeship", "US", 1990)
    assert r.data is not None and r.data.value == 380
    assert r.data.period.period_type == "statistical_year"
    assert r.data.period.period_end.isoformat() == "1990-06-30"
    assert any(w.code == "period_mismatch" for w in r.warnings)


def test_footnotes_attached(core_db: Database) -> None:
    r = get_official_figure(core_db, "civil_filings_per_judgeship", "US", 1990)
    assert r.data is not None
    assert any("June 30" in f for f in r.data.footnotes)


@pytest.mark.parametrize(
    ("args", "error", "text"),
    [
        ((W, "GU", 2024), NotPublishedError, "territorial"),
        (("total_cases_filed", "NJ", 2024), NotPublishedError, "only nationally"),
        (("civil_filings_per_judgeship", "AZ", 2012), OutOfScopeError, "2016"),
        ((W, "US", 2030), OutOfScopeError, "Available years"),
        (("nope", "US", 2020), UnknownMeasureError, "nope"),
        ((W, "SDNY", 2020), UnknownCourtError, "SDNY"),
    ],
)
def test_errors(
    core_db: Database, args: tuple[str, str, int], error: type, text: str
) -> None:
    with pytest.raises(error, match=text):
        get_official_figure(core_db, *args)


def test_edition_that_doesnt_print_the_figure(core_db: Database) -> None:
    with pytest.raises(UnknownEditionError, match="Editions that do: JB-2020"):
        get_official_figure(core_db, W, "US", 2020, "JB-2019")
    with pytest.raises(UnknownEditionError, match="Unknown edition"):
        get_official_figure(core_db, W, "US", 2020, "JB-1999")


def test_compare_courts_uses_one_edition(core_db: Database) -> None:
    r = compare_courts(core_db, "weighted_total_filings_per_judgeship", 2024, top_n=5)
    c = r.data
    assert c is not None
    assert c.edition == "JB-2024" and c.table_code == "X-1A"
    assert [x.court for x in c.rows] == ["FL-N", "NC-E", "CA-E", "TX-E", "TX-W"]
    assert [x.rank for x in c.rows] == [1, 2, 3, 4, 5]
    assert c.national is not None and c.national.edition == "JB-2024"
    assert c.national_latest is not None and c.national_latest.edition == "JFF-2024"
    assert any("Compare courts with the JB-2024" in w.message for w in r.warnings)
    assert c.total_courts == 91  # 94 districts less the 3 territorial courts
    assert c.not_published == []


def test_compare_named_courts_and_ascending(core_db: Database) -> None:
    r = compare_courts(
        core_db,
        "civil_median_months_to_disposition",
        2024,
        courts=["NY-S", "NY-E", "NJ", "GU"],
        order="asc",
    )
    c = r.data
    assert c is not None
    values = [x.value for x in c.rows]
    assert values == sorted(values)
    assert {x.court for x in c.rows} <= {"NY-S", "NY-E", "NJ", "GU"}


def test_compare_explicit_edition(core_db: Database) -> None:
    c = compare_courts(core_db, W, 2020, courts=["FL-N", "US"], edition="JB-2020").data
    assert c is not None
    assert [(x.court, x.value) for x in c.rows] == [("FL-N", 35430)]
    assert c.national is not None and c.national.value == 554
    with pytest.raises(UnknownEditionError):
        compare_courts(core_db, W, 2020, courts=["FL-N"], edition="JFF-2023")
    with pytest.raises(OutOfScopeError):
        compare_courts(core_db, W, 2012)


def test_compare_first_published(core_db: Database) -> None:
    c = compare_courts(core_db, "civil_cases_pending", 2017, courts=["WV-S"],
                       edition="first_published").data  # fmt: skip
    assert c is not None and c.edition == "JB-2017"
    latest = compare_courts(core_db, "civil_cases_pending", 2017, courts=["WV-S"]).data
    assert latest is not None and latest.edition == "JB-2018"
