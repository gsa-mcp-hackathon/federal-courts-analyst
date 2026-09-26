"""The same table from editions with different layouts parses to the same schema."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from courts_analyst.pipeline.tables.families import (
    FAMILIES,
    HeaderDriftError,
    parse,
)
from courts_analyst.pipeline.tables.grid import Cell, Grid, Row
from courts_analyst.pipeline.tables.records import SourceFile

from .test_parsers_tables import run


def _schema(family: str, year: int, fmt: str) -> tuple[set[str], set[str]]:
    res = run(family, year, fmt)
    return {o.measure_id for o in res.observations}, {o.court for o in res.observations}


@pytest.mark.parametrize(
    ("family", "a", "b"),
    [
        # X-1A: 2016 PDF puts Total last; 2025 PDF puts Total first.
        ("jb_x1a", (2016, "pdf"), (2025, "pdf")),
        ("jb_x1a", (2016, "pdf"), (2020, "xlsx")),
        # JFF 6.2 puts Weighted before Unweighted, unlike X-1A.
        ("jff_6.2", (2023, "xlsx"), (2025, "pdf")),
        # C-1 changed from 4 columns per group to 3 in 2023.
        ("jb_c1", (2020, "xlsx"), (2023, "xlsx")),
        ("jb_c1", (2016, "pdf"), (2024, "pdf")),
        # C-5: "Trial" vs "During Trial", centred vs offset group labels.
        ("jb_c5", (2016, "pdf"), (2020, "xlsx")),
        ("jb_c5", (2017, "pdf"), (2020, "xlsx")),
    ],
)
def test_same_schema_across_editions(
    family: str, a: tuple[int, str], b: tuple[int, str]
) -> None:
    ma, ca = _schema(family, *a)
    mb, cb = _schema(family, *b)
    assert FAMILIES[family].required <= ma
    assert ma == mb
    assert ca == cb


def test_column_order_drift_maps_by_label() -> None:
    """2016 lists Civil first, 2025 lists Total first; values still land right."""
    old = {
        o.measure_id: o.raw
        for o in run("jb_x1a", 2016, "pdf").observations
        if o.court == "US"
    }
    new = {
        o.measure_id: o.raw
        for o in run("jb_x1a", 2025, "pdf").observations
        if o.court == "US"
    }
    assert old["weighted_total_filings_per_judgeship"] == "489"
    assert old["weighted_civil_filings_per_judgeship"] == "355"
    assert new["weighted_total_filings_per_judgeship"] == "534"
    assert new["weighted_civil_filings_per_judgeship"] == "414"


X1A_HEADERS = [
    "Judgeships",
    "Unweighted Filings per Judgeship Civil",
    "Unweighted Filings per Judgeship Criminal",
    "Unweighted Filings per Judgeship Supervision Hearings",
    "Unweighted Filings per Judgeship Total",
    "Weighted Filings per Judgeship Civil",
    "Weighted Filings per Judgeship Criminal",
    "Weighted Filings per Judgeship Supervision Hearings",
    "Weighted Filings per Judgeship Total",
]


def _grid(headers: list[str]) -> Grid:
    cells: list[Cell | None] = [
        Cell("1", 1.0, 0, (), f"S!{c}6") for c in "BCDEFGHIJ"[: len(headers)]
    ]
    return Grid(
        title="Table X-1A.", headers=headers, rows=[Row("Total", (), "S!A6", cells)]
    )


def _src() -> SourceFile:
    return SourceFile(
        file_id="JB-2020:X-1A:xlsx",
        url="u",
        sha256="0",
        series=FAMILIES["jb_x1a"].series,
        table_code="X-1A",
        edition="JB-2020",
        period_end=date(2020, 9, 30),
        format="xlsx",
    )


def test_unknown_header_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A renamed column we don't recognise fails loudly instead of dropping data."""
    import courts_analyst.pipeline.tables.families as fam_mod

    headers = list(X1A_HEADERS)
    headers[5] = "Weighted Filings per Judgeship Civil Cases (new name)"  # drifted
    monkeypatch.setattr(fam_mod, "read_grid", lambda f, p: _grid(headers))
    with pytest.raises(HeaderDriftError, match="weighted_civil_filings_per_judgeship"):
        parse(FAMILIES["jb_x1a"], _src(), Path("x.xlsx"))


def test_duplicate_mapping_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import courts_analyst.pipeline.tables.families as fam_mod

    base = list(X1A_HEADERS)
    base[8] = "Weighted Filings per Judgeship Civil"  # two columns claim one measure
    monkeypatch.setattr(fam_mod, "read_grid", lambda f, p: _grid(base))
    with pytest.raises(HeaderDriftError):
        parse(FAMILIES["jb_x1a"], _src(), Path("x.xlsx"))


def test_page_headers_must_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    import courts_analyst.pipeline.tables.families as fam_mod

    good = list(X1A_HEADERS)
    g = _grid(good)
    g.page_headers = [good, list(reversed(good))]
    monkeypatch.setattr(fam_mod, "read_grid", lambda f, p: g)
    with pytest.raises(HeaderDriftError, match="page 2"):
        parse(FAMILIES["jb_x1a"], _src(), Path("x.pdf"))
