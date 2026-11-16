"""Numeric scoring: printed precision, tolerances, and figure extraction."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.numbers import round_half_up
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure
from courts_analyst.evaluation.schema import ExpectedFigure
from courts_analyst.evaluation.scoring.figures import (
    figures_in_text,
    find_editions,
    reported_figures,
)
from courts_analyst.evaluation.scoring.numeric import (
    check_figures,
    printed_decimals,
    value_matches,
)


def exp(value: float, **kw: object) -> ExpectedFigure:
    return ExpectedFigure.model_validate({"value": value, **kw})


@pytest.mark.parametrize(
    ("reported", "ok"),
    [(322, True), (322.2, True), (321.6, True), (321.4, False), (322.5, False)],
)
def test_printed_precision(reported: float, ok: bool) -> None:
    assert value_matches(reported, exp(322)) is ok


def test_one_decimal_precision() -> None:
    assert value_matches(13.7049, exp(13.7))
    assert not value_matches(13.76, exp(13.7))
    assert printed_decimals(13.7) == 1
    assert printed_decimals(5.5) == 1
    assert printed_decimals(470581.0) == 0


def test_absolute_and_relative_tolerance() -> None:
    assert value_matches(470000, exp(470581, tolerance_pct=0.5))
    assert not value_matches(460000, exp(470581, tolerance_pct=0.5))
    assert value_matches(330, exp(322, tolerance=10))
    assert not value_matches(333, exp(322, tolerance=10))


@given(
    st.floats(min_value=0, max_value=1e6, allow_nan=False),
    st.integers(min_value=0, max_value=2),
)
def test_unrounded_value_matches_its_printed_form(value: float, decimals: int) -> None:
    """An answer quoting more digits than the table prints still matches,
    except exactly on a rounding boundary."""
    shown = round_half_up(value, decimals)
    if abs(value - shown) < 0.5 * 10**-decimals - 1e-6:
        assert value_matches(value, exp(shown))


@given(st.floats(min_value=1, max_value=1e6, allow_nan=False), st.floats(0.01, 5))
def test_relative_tolerance_is_symmetric(value: float, pct: float) -> None:
    e = exp(value, tolerance_pct=pct)
    delta = value * pct / 100 * 0.999
    assert value_matches(value + delta, e)
    assert value_matches(value - delta, e)


def test_units_per_judgeship_vs_totals() -> None:
    """A per-judgeship value never satisfies a total, even when both are big."""
    assert not value_matches(554, exp(470581, tolerance_pct=1))
    assert not value_matches(470581, exp(554))


def test_numbers_in_text() -> None:
    figs = figures_in_text(
        "In FY2020 the national figure was 322 (JFF-2023); JB-2020 first "
        "published 554. Table 6.2 and X-1A; 470,581 cases; MDL 2885."
    )
    values = [f.value for f in figs]
    assert 322 in values and 554 in values and 470581 in values
    assert 2020 not in values  # FY2020 and JB-2020 are not figures
    assert 6.2 not in values and 2885 not in values
    by_value = {f.value: f.edition for f in figs}
    assert by_value[322] == "JFF-2023"
    assert by_value[554] == "JB-2020"


@pytest.mark.parametrize(
    ("text", "edition"),
    [
        ("JFF-2023", "JFF-2023"),
        ("JB 2020", "JB-2020"),
        ("Judicial Business 2020", "JB-2020"),
        ("Judicial Business of the United States Courts, 2020", "JB-2020"),
        ("the 2023 Judicial Facts and Figures", "JFF-2023"),
        ("the 2023 edition of Judicial Facts and Figures", "JFF-2023"),
        ("Judicial Facts & Figures (2024)", "JFF-2024"),
        ("Judicial Facts and Figures, Table 6.2, 2025", "JFF-2025"),
    ],
)
def test_edition_mentions(text: str, edition: str) -> None:
    assert [m.edition for m in find_editions(text)] == [edition]


def test_nearest_edition_prefers_following_mention() -> None:
    figs = figures_in_text("554 in JB-2020 was revised to 322 in JFF-2023.")
    assert {f.value: f.edition for f in figs} == {554: "JB-2020", 322: "JFF-2023"}


def test_far_edition_does_not_pair() -> None:
    text = "The value was 322. " + "Other context follows here. " * 4 + "See JFF-2023."
    assert figures_in_text(text)[0].edition is None


def test_edition_later_in_the_same_sentence_pairs() -> None:
    text = (
        "**37,003** civil cases were filed in the Eleventh Circuit's district courts "
        "(N.D. Ga., M.D. Ga., S.D. Ga., N.D. Fla., M.D. Fla., S.D. Fla., N.D. Ala., "
        "M.D. Ala., S.D. Ala.) in FY2025 (JB-2025, Table C-1)."
    )
    assert figures_in_text(text)[0] == ReportedFigure(value=37003, edition="JB-2025")


def test_cited_figures_come_first() -> None:
    rec = AnswerRecord(
        question_id="q",
        answerer="t",
        final_text="about 300",
        cited_figures=[ReportedFigure(value=322, edition="JFF-2023")],
    )
    assert reported_figures(rec)[0] == ReportedFigure(value=322, edition="JFF-2023")


def test_all_vs_any_modes() -> None:
    both = [exp(322, edition="JFF-2023"), exp(554, edition="JB-2020")]
    one = [ReportedFigure(value=322, edition="JFF-2023")]
    assert not check_figures(both, "all", one).edition_ok
    assert check_figures(both, "any", one).edition_ok
    none = check_figures(both, "all", [])
    assert not none.numeric_ok and none.needs_edition


@pytest.mark.parametrize("sep", [" ", " "])
def test_typographic_thousands_separator_is_one_number(sep: str) -> None:
    """The wxO agent writes "297 877 (JB-2019)"; that is one figure."""
    text = f"Civil cases filed in FY2019: **297{sep}877 (JB-2019, Table C-1)**."
    assert figures_in_text(text) == [ReportedFigure(value=297877, edition="JB-2019")]
    assert figures_in_text(f"1{sep}234{sep}567 cases")[0].value == 1234567
    rec = AnswerRecord(question_id="q", answerer="t", final_text=text)
    result = check_figures(
        [exp(297877, edition="JB-2019")], "all", reported_figures(rec)
    )
    assert result.numeric_ok and result.edition_ok


@pytest.mark.parametrize(
    "text",
    [
        "297 877 cases",  # an ASCII space can separate two numbers
        "297 8770 cases",  # not a three-digit group
        "297 877 cases",  # no-break space: used between words and numbers
    ],
)
def test_other_spaces_still_split_numbers(text: str) -> None:
    assert figures_in_text(text)[0].value == 297
