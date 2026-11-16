"""Table parsers on real committed files, one family at a time, xlsx and PDF.

Snapshots pin the header → measure mapping and a few parsed rows per file,
so a parser change that moves any number shows up in review.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from courts_analyst.pipeline.tables.families import FAMILIES, parse
from courts_analyst.pipeline.tables.records import SourceFile, edition_id

FIX = Path(__file__).parent / "fixtures" / "tables"

CASES = [
    ("jb_x1a", 2020, "xlsx"),
    ("jb_x1a", 2020, "pdf"),
    ("jb_x1a", 2016, "pdf"),
    ("jb_x1a", 2025, "pdf"),
    ("jff_6.2", 2023, "xlsx"),
    ("jff_6.2", 2025, "pdf"),
    ("jb_c1", 2020, "xlsx"),
    ("jb_c1", 2023, "xlsx"),
    ("jb_c1", 2016, "pdf"),
    ("jb_c1", 2024, "pdf"),
    ("jb_c5", 2020, "xlsx"),
    ("jb_c5", 2016, "pdf"),
    ("jb_c5", 2017, "pdf"),
    ("jff_6.1", 2023, "xlsx"),
    ("jff_6.1", 2025, "pdf"),
    ("jff_6.3", 2023, "xlsx"),
    ("jff_6.3", 2023, "pdf"),
]


def run(family_key: str, year: int, fmt: str):  # type: ignore[no-untyped-def]
    fam = FAMILIES[family_key]
    end = date(year, 9, 30)
    ed = edition_id(fam.series, end)
    path = FIX / ed / f"{fam.stem}_0930.{year}.{fmt}"
    src = SourceFile(
        file_id=f"{ed}:{fam.table_code}:{fmt}",
        url=f"https://example.test/{path.name}",
        sha256="0" * 64,
        series=fam.series,
        table_code=fam.table_code,
        edition=ed,
        period_end=end,
        format=fmt,
    )
    return parse(fam, src, path)


@pytest.mark.parametrize(("family", "year", "fmt"), CASES, ids=lambda v: str(v))
def test_parser_snapshot(family: str, year: int, fmt: str, snapshot) -> None:  # type: ignore[no-untyped-def]
    res = run(family, year, fmt)
    assert res.observations
    assert res.warnings == []
    assert res.unmapped_headers == []
    summary = {
        "title": res.title.splitlines()[0],
        "measures": sorted({o.measure_id for o in res.observations}),
        "courts": len({o.court for o in res.observations}),
        "fiscal_years": sorted({o.fiscal_year for o in res.observations}),
        "observations": len(res.observations),
        "footnotes": [(f.marker, f.text[:60]) for f in res.footnotes],
        "national": sorted(
            (o.measure_id, o.fiscal_year, o.raw)
            for o in res.observations
            if o.court == "US" and o.fiscal_year in (year, 2020)
        ),
    }
    assert summary == snapshot


def test_fy_from_header_and_june_period() -> None:
    """C-1 prior-year pending gets FY-1; JFF 1990 row is a June 30 period."""
    c1 = run("jb_c1", 2020, "xlsx")
    prior = [o for o in c1.observations if o.fiscal_year == 2019]
    assert prior and {o.measure_id.split("civil_cases_")[1] for o in prior} == {
        "pending"
    }
    assert all(o.period_end == date(2019, 9, 30) for o in prior)
    j62 = run("jff_6.2", 2023, "xlsx")
    y1990 = [o for o in j62.observations if o.fiscal_year == 1990]
    assert y1990 and all(o.period_end == date(1990, 6, 30) for o in y1990)
    assert all(
        o.period_end == date(2020, 9, 30)
        for o in j62.observations
        if o.fiscal_year == 2020
    )


def test_footnotes_attach_to_columns_and_rows() -> None:
    res = run("jff_6.2", 2023, "xlsx")
    fn = {f.footnote_id: f for f in res.footnotes}
    judges = next(
        o
        for o in res.observations
        if o.measure_id == "authorized_judgeships" and o.fiscal_year == 2020
    )
    assert any("territorial" in fn[i].text for i in judges.footnote_ids)
    old = next(
        o
        for o in res.observations
        if o.measure_id == "authorized_judgeships" and o.fiscal_year == 1990
    )
    assert any("June 30" in fn[i].text for i in old.footnote_ids)


def test_dash_is_a_null_value_not_dropped() -> None:
    res = run("jb_c5", 2020, "xlsx")
    me = [
        o
        for o in res.observations
        if o.court == "ME" and o.measure_id == "civil_median_months_court_action_trial"
    ]
    assert len(me) == 1 and me[0].value is None and me[0].raw == "-"


def test_district_coverage() -> None:
    """X-1A covers 90 non-territorial districts + PR... all 91 plus the total."""
    res = run("jb_x1a", 2020, "xlsx")
    courts = {o.court for o in res.observations}
    assert len(courts) == 92 and "US" in courts
    assert not courts & {"VI", "GU", "MP"}  # territorial courts excluded (table note)
    c1 = run("jb_c1", 2023, "xlsx")
    assert {"VI", "GU", "MP", "CIR-11", "CIR-01"} <= {o.court for o in c1.observations}
