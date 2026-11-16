"""Unit tests for grid helpers, footnote splitting and display rounding."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.numbers import round_half_up
from courts_analyst.pipeline.tables import grid
from courts_analyst.pipeline.tables.families import FAMILIES, row_test, split_footnotes
from courts_analyst.pipeline.tables.grid import (
    GridError,
    _Column,
    _decimals_from_format,
    _general_decimals,
    _group_blocks,
    _midpoint_blocks,
    _Word,
    normalize_header,
    parse_number,
    split_markers,
)
from courts_analyst.pipeline.tables.records import Series, edition_id

FIX = Path(__file__).parent / "fixtures" / "tables"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("673", (673.0, 0, True)),
        ("51,153", (51153.0, 0, True)),
        ("38.3", (38.3, 1, True)),
        ("-", (None, None, True)),
        ("—", (None, None, True)),
        ("NA", (None, None, True)),
        ("(12)", (-12.0, 0, True)),
        (".5", (0.5, 1, True)),
        ("Total", (None, None, False)),
        ("1ST", (None, None, False)),
    ],
)
def test_parse_number(text: str, expected: tuple[object, ...]) -> None:
    assert parse_number(text) == expected


def test_split_markers() -> None:
    assert split_markers("Judgeships ¹") == ("Judgeships", ("¹",))
    assert split_markers("1990 ³") == ("1990", ("³",))
    assert split_markers("2015¹²") == ("2015", ("¹", "²"))


def test_normalize_header() -> None:
    assert normalize_header("U.S. Civil Cases Pending September  30, 2019¹") == (
        "us civil cases pending september 30 2019"
    )


@pytest.mark.parametrize(
    ("fmt", "dec"),
    [
        ("General", None),
        (None, None),
        ("0", 0),
        ("#,##0", 0),
        ("0.0", 1),
        ("#,##0.00;(#,##0.00)", 2),
        ("@", None),
    ],
)
def test_decimals_from_format(fmt: str | None, dec: int | None) -> None:
    assert _decimals_from_format(fmt) == dec


def test_general_decimals() -> None:
    assert _general_decimals(673.0) == 0
    assert _general_decimals(38.3) == 1
    assert _general_decimals(3.67320474777448) == 9


@pytest.mark.parametrize(
    ("value", "dec", "out"),
    [
        (458.5, 0, 459.0),
        (20.25, 1, 20.3),
        (4.05, 1, 4.1),
        (-2.5, 0, -3.0),
        (553.954918, 0, 554.0),
    ],
)
def test_round_half_up(value: float, dec: int, out: float) -> None:
    assert round_half_up(value, dec) == out


@given(st.integers(min_value=-(10**7), max_value=10**7))
def test_round_half_up_halves(n: int) -> None:
    """x.5 always rounds away from zero (Excel), unlike Python's round()."""
    x = n + 0.5
    assert (
        abs(round_half_up(x)) == abs(n) + 1
        if n >= 0
        else abs(round_half_up(x)) == abs(n)
    )


def test_split_footnotes() -> None:
    notes = [
        "Note: Due to a change in methodology, numbers may differ.\n"
        "Weighted filings are based on 2016 weights.\n"
        "¹ Authorized judgeships include territorial courts.\n"
        "² Beginning in 2002, hearings are included.",
        "Source: Table X-1A,",
    ]
    out = split_footnotes(notes)
    assert out[0][0] is None and "2016 weights" in out[0][1]
    assert out[1] == ("¹", "Authorized judgeships include territorial courts.")
    assert out[2][0] == "²"
    assert out[3] == (None, "Source: Table X-1A,")


def test_edition_ids() -> None:
    from datetime import date

    assert edition_id(Series.JB, date(2020, 9, 30)) == "JB-2020"
    assert edition_id(Series.STFJ, date(2024, 6, 30)) == "STFJ-2024-06"
    assert edition_id(Series.FJCS, date(2024, 9, 30)) == "FJCS-2024"


def _cols(*xs: float) -> list[_Column]:
    return [_Column(x - 6, x + 6) for x in xs]


def test_midpoint_blocks_like_x1a() -> None:
    cols = _cols(137, 218, 299, 380, 460, 550, 623, 712, 794)
    groups = [_Word("Unweighted", 263, 394, 0), _Word("Weighted", 592, 713, 0)]
    assert _midpoint_blocks(groups, cols) == [(1, 4), (5, 8)]


def test_centered_blocks_like_c5() -> None:
    cols = _cols(188, 250, 306, 360, 411, 470, 521, 585, 636, 710)
    groups = [
        _Word("Total Cases", 198, 243, 0),
        _Word("No Court Action", 300, 362, 0),
        _Word("Court Action", 545, 593, 0),
    ]
    assert _group_blocks(groups, cols) == [(0, 1), (2, 3), (4, 9)]


def test_centered_blocks_follow_leaf_pattern() -> None:
    """Off-centre labels (JB-2017 C-5) still land on Number/Median pairs."""
    cols = _cols(120, 182, 233, 295, 344, 411, 462, 528, 581, 645)
    leaves = ["number of cases", "median time interval in months"] * 5
    groups = [
        _Word("Before Pretrial", 337, 387, 0),
        _Word("During or After Pretrial", 439, 518, 0),
        _Word("During Trial", 575, 616, 0),
    ]
    assert _group_blocks(groups, cols, leaves) == [(4, 5), (6, 7), (8, 9)]


def test_no_groups() -> None:
    assert _midpoint_blocks([], _cols(1, 2)) is None
    assert _group_blocks([], _cols(1, 2)) is None


def test_read_xlsx_rejects_non_table(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active["A1"] = "hello"  # type: ignore[index]
    p = tmp_path / "x.xlsx"
    wb.save(p)
    with pytest.raises(GridError, match="no table title"):
        grid.read_xlsx(p, lambda s: True)
    wb.active["A1"] = "Table Z-9"  # type: ignore[index]
    wb.save(p)
    with pytest.raises(GridError, match="no data rows"):
        grid.read_xlsx(p, lambda s: False)


def test_read_pdf_rejects_unrecognised_rows() -> None:
    with pytest.raises(GridError, match="no data rows"):
        grid.read_pdf(FIX / "JB-2016" / "jb_x1a_0930.2016.pdf", lambda s: False)


def test_small_digit_footnote_markers_become_superscripts() -> None:
    """JB-2016 C-1 prints the '1' after 'Sept. 30, 2015' as a small plain digit."""
    fam = FAMILIES["jb_c1"]
    g = grid.read_pdf(
        FIX / "JB-2016" / "jb_c1_0930.2016.pdf", row_test("court"), fam.group_headers
    )
    assert any("2015¹" in h for h in g.headers)
    assert len(g.page_headers) >= 2  # continuation page repeats the header
