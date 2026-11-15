"""The request desk's verification gate (ADR 0013, decision 5), on the real
fixture catalog: FY2020 national weighted civil filings per judgeship is 554
in JB-2020 to JFF-2022 and 322 from JFF-2023; FY2021 is 434 then 318."""

from __future__ import annotations

from typing import Any

import pytest

from courts_analyst.core.desk.gate import verify
from courts_analyst.core.desk.models import CitationIn

W = "weighted_civil_filings_per_judgeship"


def cite(fy: int, edition: str, value: float, court: str = "US", m: str = W) -> Any:
    return CitationIn(
        measure=m, court=court, fiscal_year=fy, edition=edition, value=value
    )


def codes(report: Any) -> list[str]:
    return [p.code for p in report.problems]


def test_consistent_answer_passes(core_db: Any) -> None:
    r = verify(
        core_db,
        "National weighted civil filings per judgeship were 322 in FY2020 and 318 "
        "in FY2021 (JFF-2024).",
        [cite(2020, "JFF-2024", 322), cite(2021, "JFF-2024", 318)],
    )
    assert r.passed, r.problems
    assert r.edition_basis == ["JFF-2024"]
    assert {c.value for c in r.citations} == {322, 318}
    assert r.numbers_checked == 2


def test_first_published_value_next_to_current_ones_is_refused(core_db: Any) -> None:
    r = verify(
        core_db,
        "National weighted civil filings per judgeship were 554 in FY2020 and 318 "
        "in FY2021.",
        [cite(2020, "JB-2020", 554), cite(2021, "JFF-2024", 318)],
    )
    assert not r.passed
    assert codes(r) == ["mixed_editions"]
    p = r.problems[0]
    assert p.number in {"554", "318"}
    assert "first-published" in (p.fix or "") or "edition" in (p.fix or "")


def test_same_series_contradiction_is_refused(core_db: Any) -> None:
    # JFF-2022 still prints 554 for FY2020; JFF-2024 prints 322.
    r = verify(
        core_db,
        "FY2020: 554. FY2021: 318. FY2022: 309.",
        [
            cite(2020, "JFF-2022", 554),
            cite(2021, "JFF-2024", 318),
            cite(2022, "JFF-2024", 309),
        ],
    )
    assert codes(r) == ["mixed_editions"]
    assert r.problems[0].number == "554"
    assert "Use 322 (JFF-2024)" in (r.problems[0].fix or "")


def test_earlier_value_labelled_as_history_passes(core_db: Any) -> None:
    r = verify(
        core_db,
        "FY2020 was 322 (JFF-2024); it was first published as 554 in JB-2020. "
        "FY2021 was 318.",
        [
            cite(2020, "JB-2020", 554),
            cite(2020, "JFF-2024", 322),
            cite(2021, "JFF-2024", 318),
        ],
    )
    assert r.passed, r.problems
    history = {c.value: c.historical for c in r.citations}
    assert history == {554: True, 322: False, 318: False}
    assert r.edition_basis == ["JFF-2024"]


@pytest.mark.parametrize(
    "text",
    [
        # The answer watsonx Orchestrate's agent wrote: "updated", not "revised".
        "National weighted civil filings per judgeship in FY 2020 are:\n\n"
        "* **322 (JFF\u20112025)** \u2013 the latest official figure.\n"
        "* **554 (JB\u20112020)** \u2013 the value first published in the Judicial "
        "Business edition and used through JFF\u20112022.\n\n"
        "The two values exist because the statistic was revised in later editions. "
        "The Judicial Business of the United States Courts (JB\u20112020) reported "
        "554 filings per judgeship, but the Judicial Facts and Figures series "
        "(JFF\u20112023 onward) updated the number to 322.",
        # Both editions' values side by side, no revision wording.
        "FY2020: 554 (JB-2020) and 322 (JFF-2025).",
    ],
)
def test_earlier_value_beside_a_change_passes(core_db: Any, text: str) -> None:
    r = verify(core_db, text, [cite(2020, "JB-2020", 554), cite(2020, "JFF-2025", 322)])
    assert r.passed, r.problems
    assert {c.value: c.historical for c in r.citations} == {554: True, 322: False}


@pytest.mark.parametrize(
    ("hyphen", "space"), [("\u2011", "\u202f"), ("\u2010", "\u00a0"), ("-", " ")]
)
def test_typographic_dashes_and_spaces_read_as_ascii(
    core_db: Any, hyphen: str, space: str
) -> None:
    # The wxO agent's retries after a refusal (2026-11-14 desk tests) wrote
    # "first\u2011published" with a no-break hyphen and were refused as mixed editions.
    text = (
        f"Weighted civil filings per judgeship nationally in FY{space}2020 was "
        f"322 (JFF{hyphen}2025). The figure had previously been 554 (JB{hyphen}2020), "
        f"the first{hyphen}published value."
    )
    r = verify(core_db, text, [cite(2020, "JFF-2025", 322), cite(2020, "JB-2020", 554)])
    assert r.passed, r.problems
    assert {c.value: c.historical for c in r.citations} == {554: True, 322: False}


def test_earlier_value_alone_in_a_sentence_is_refused(core_db: Any) -> None:
    r = verify(
        core_db,
        "FY2020 was 322 (JFF-2025). The figure was 554 (JB-2020).",
        [cite(2020, "JB-2020", 554), cite(2020, "JFF-2025", 322)],
    )
    assert codes(r) == ["mixed_editions"]
    assert r.problems[0].number == "554"


def test_uncited_number_is_refused(core_db: Any) -> None:
    r = verify(
        core_db,
        "It was 322 in FY2020, or about 400 a judge.",
        [cite(2020, "JFF-2024", 322)],
    )
    assert codes(r) == ["uncited_number"]
    assert r.problems[0].number == "400"


@pytest.mark.parametrize(
    ("citation", "code"),
    [
        (cite(2020, "JFF-2024", 323), "wrong_value"),
        (cite(2020, "JFF-2016", 322), "unknown_figure"),
        (cite(2020, "JFF-2024", 322, m="no_such_measure"), "unknown_figure"),
    ],
)
def test_bad_citation_is_refused_once(core_db: Any, citation: Any, code: str) -> None:
    r = verify(core_db, f"It was {citation.value:g} in FY2020.", [citation])
    assert codes(r) == [code]


def test_wrong_value_names_the_printed_one(core_db: Any) -> None:
    r = verify(core_db, "It was 323.", [cite(2020, "JFF-2024", 323)])
    assert r.problems[0].fix == "Use 322 (JFF-2024)."


def test_years_thresholds_and_differences_need_no_citation(core_db: Any) -> None:
    r = verify(
        core_db,
        "In FY2020 the figure was 322 in JFF-2024, revised down by 232 from the "
        "554 first published in JB-2020; the Judicial Conference's bar is 430 "
        "and 600 marks an emergency (Table 6.2).",
        [cite(2020, "JFF-2024", 322), cite(2020, "JB-2020", 554)],
    )
    assert r.passed, r.problems


def test_advocacy_is_refused(core_db: Any) -> None:
    r = verify(
        core_db,
        "At 322 in FY2020 (JFF-2024), the courts clearly need more judges.",
        [cite(2020, "JFF-2024", 322)],
    )
    assert codes(r) == ["advocacy"]


def test_empty_answer_is_refused(core_db: Any) -> None:
    assert codes(verify(core_db, "   ", [])) == ["empty"]


def test_cited_but_unquoted_figures_are_dropped(core_db: Any) -> None:
    r = verify(
        core_db,
        "It was 322 in FY2020 (JFF-2024).",
        [cite(2020, "JFF-2024", 322), cite(2021, "JFF-2024", 318)],
    )
    assert r.passed
    assert [c.value for c in r.citations] == [322]


def test_thousands_separators_and_district_figures(core_db: Any) -> None:
    r = verify(
        core_db,
        "N.D. Fla. had 35,430 weighted civil filings per judgeship in FY2020 "
        "(JB-2020), against a national 554 in the same edition.",
        [cite(2020, "JB-2020", 35430, court="FL-N"), cite(2020, "JB-2020", 554)],
    )
    assert r.passed, r.problems


def test_edition_named_in_the_text_must_match_the_citation(core_db: Any) -> None:
    r = verify(
        core_db, "It was 322 (JB-2020) in FY2020.", [cite(2020, "JFF-2024", 322)]
    )
    assert codes(r) == ["edition_label"]
    assert r.problems[0].fix == "Label it JFF-2024, or cite JB-2020's value."
    ok = verify(
        core_db, "It was 322 (JFF-2024) in FY2020.", [cite(2020, "JFF-2024", 322)]
    )
    assert ok.passed


def test_links_dockets_and_dates_are_not_statistics(core_db: Any) -> None:
    r = verify(
        core_db,
        "It was 322 in FY2020 (JFF-2024). See docket 3:19-md-02885, filed "
        "2020-07-06, and the national emergency of March 13, 2020; "
        "[search](https://example.org/?q=%2220-cv-49045%22) or `MDL 2885`.",
        [cite(2020, "JFF-2024", 322)],
    )
    assert r.passed, r.problems


def test_server_computed_values_and_derived_percentages(core_db: Any) -> None:
    text = "From 381 (JB-2019) to 554 (JB-2020), up 45%; N.D. Fla. added 206 points."
    cites = [cite(2019, "JB-2019", 381), cite(2020, "JB-2020", 554)]
    refused = verify(core_db, text, cites)
    assert codes(refused) == ["uncited_number"] and refused.problems[0].number == "206"
    ok = verify(core_db, text, cites, computed={206.0: "explain_change"})
    assert ok.passed, ok.problems
    assert [(c.number, c.source) for c in ok.computed] == [("206", "explain_change")]


def test_a_range_label_is_right_when_every_edition_prints_the_value(
    core_db: Any,
) -> None:
    # JFF-2023 to JFF-2025 all print 322: labelling it with the first is true.
    r = verify(
        core_db,
        "FY2020 was 554 (JB-2020), later revised to 322 (JFF-2023 to JFF-2025).",
        [cite(2020, "JB-2020", 554), cite(2020, "JFF-2025", 322)],
    )
    assert r.passed, r.problems
    # JFF-2022 still printed 554, so "322 (JFF-2022)" is a wrong label.
    bad = verify(core_db, "It was 322 (JFF-2022).", [cite(2020, "JFF-2025", 322)])
    assert codes(bad) == ["edition_label"]
