"""explain_term: glossary, measures, NOS codes, and suggestions."""

from __future__ import annotations

import pytest

from courts_analyst.core.glossary import explain_term, glossary
from courts_analyst.core.measures import registry


@pytest.mark.parametrize(
    ("query", "term", "kind"),
    [
        ("weighted filings", "weighted filings", "glossary"),
        ("Weighted Filings!", "weighted filings", "glossary"),
        ("MDL", "multidistrict litigation", "glossary"),
        ("directly filed MDL", "directly filed MDL case", "glossary"),
        ("statistical year", "statistical year", "glossary"),
        ("JFF", "judicial facts and figures", "glossary"),
        ("civil_cases_pending", "Civil cases pending", "measure"),
        ("nature of suit 442", "Nature of suit 442", "nature_of_suit"),
        ("NOS 830", "Nature of suit 830", "nature_of_suit"),
        ("442", "Nature of suit 442", "nature_of_suit"),
    ],
)
def test_lookups(query: str, term: str, kind: str) -> None:
    r = explain_term(query).data
    assert r is not None and r.found and r.definition is not None
    assert (r.definition.term, r.definition.kind) == (term, kind)


def test_nos_442_is_employment_civil_rights() -> None:
    d = explain_term("nature of suit 442").data.definition  # type: ignore[union-attr]
    assert d is not None and "mploy" in d.definition
    assert d.nos_group == "Civil Rights"


def test_unknown_term_suggests() -> None:
    r = explain_term("weighted fillings")
    assert r.data is not None and not r.data.found
    assert "weighted filings" in r.data.did_you_mean
    assert r.warnings and "Did you mean" in r.warnings[0].message
    nothing = explain_term("qwertyuiop").data
    assert nothing is not None and nothing.did_you_mean == []
    assert explain_term("999").data.found is False  # type: ignore[union-attr]


def test_glossary_entries_are_complete_and_unique() -> None:
    names: set[str] = set()
    for e in glossary():
        assert e["definition"] and e["source"], e["term"]
        for n in [e["term"], *e.get("aliases", [])]:
            key = str(n).lower()
            assert key not in names, n
            names.add(key)
        see = e.get("see_also")
        if see:
            assert see in registry(), see


@pytest.mark.parametrize(
    ("query", "code", "matches"),
    [
        # The live agent guessed 442 and then 430 for "patent cases".
        ("patent", "830", ["830", "835"]),
        ("patent cases", "830", ["830", "835"]),
        ("Patents", "830", ["830", "835"]),
        ("employment discrimination", "442", ["442"]),
        ("copyright", "820", ["820"]),
        ("trademark infringement", "840", ["840"]),
        ("medical malpractice", "362", ["362"]),
        ("ERISA", "791", ["791"]),
        ("social security disability", "863", ["863"]),
    ],
)
def test_case_types_in_words_find_their_codes(
    query: str, code: str, matches: list[str]
) -> None:
    r = explain_term(query).data
    assert r is not None and r.found and r.definition is not None
    assert r.definition.nos_code == code
    assert [m.code for m in r.nos_matches] == matches


def test_a_group_name_returns_the_whole_group() -> None:
    r = explain_term("civil rights").data
    assert r is not None and r.definition is not None
    assert r.definition.nos_group == "Civil Rights" and r.definition.nos_code is None
    assert "nos_groups=['Civil Rights']" in r.definition.definition
    assert {m.code for m in r.nos_matches} >= {"440", "442", "445", "446"}
    ip = explain_term("intellectual property").data
    assert ip is not None and ip.definition is not None
    assert ip.definition.nos_group == "Intellectual Property Rights"


def test_several_partial_matches_are_listed_not_picked() -> None:
    r = explain_term("personal injury").data
    assert r is not None and r.definition is not None
    assert r.definition.nos_code is None
    assert len(r.nos_matches) > 1
    assert "Several nature-of-suit codes match" in r.definition.definition


def test_glossary_and_measures_still_win_over_codebook_labels() -> None:
    weighted = explain_term("weighted filings").data
    assert weighted is not None and weighted.definition is not None
    assert weighted.definition.kind == "glossary" and weighted.nos_matches == []
    assert explain_term("civil filings").data.found is False  # type: ignore[union-attr]
    assert explain_term("qwertyuiop").data.nos_matches == []  # type: ignore[union-attr]
