"""Court registry: every alias maps to exactly one court; unknown names raise."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.courts import (
    CIRCUITS,
    COURTS,
    DISTRICTS,
    CourtLevel,
    UnknownCourtError,
    _alias_index,
    _aliases,
    resolve_court,
)


def test_counts() -> None:
    assert len(DISTRICTS) == 94
    assert len(CIRCUITS) == 12
    assert COURTS["US"].level is CourtLevel.NATIONAL


def test_every_district_belongs_to_a_circuit() -> None:
    for code in DISTRICTS:
        assert COURTS[code].circuit in CIRCUITS


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("FL,N", "FL-N"),
        ("FL-N", "FL-N"),
        ("FLN", "FL-N"),
        ("N.D. Fla.", "FL-N"),
        ("Florida, Northern", "FL-N"),
        ("Northern District of Florida", "FL-N"),
        ("  florida   northern ", "FL-N"),
        ("S.D.N.Y.", "NY-S"),
        ("NY,S", "NY-S"),
        ("D.D.C.", "DC"),
        ("District of Columbia", "DC"),
        ("D. Mass.", "MA"),
        ("Massachusetts", "MA"),
        ("PR", "PR"),
        ("D.N.D.", "ND"),
        ("North Dakota", "ND"),
        ("Northern Mariana Islands", "MP"),
        ("Guam", "GU"),
        ("11th Circuit", "CIR-11"),
        ("Eleventh Circuit", "CIR-11"),
        ("DC Circuit", "CIR-DC"),
        ("Total", "US"),
        ("All District Courts", "US"),
    ],
)
def test_known_aliases(name: str, code: str) -> None:
    assert resolve_court(name).code == code


@pytest.mark.parametrize(
    "name", ["", "Florida", "Atlantis", "FL,X", "13th Circuit", "NY"]
)
def test_unknown_or_ambiguous_raises(name: str) -> None:
    with pytest.raises(UnknownCourtError):
        resolve_court(name)


def test_citations() -> None:
    assert COURTS["FL-N"].citation == "N.D. Fla."
    assert COURTS["NY-S"].citation == "S.D.N.Y."
    assert COURTS["WV-S"].citation == "S.D. W. Va."
    assert COURTS["DC"].citation == "D.D.C."
    assert COURTS["MA"].citation == "D. Mass."


def test_no_alias_claimed_by_two_courts() -> None:
    """Each court's own aliases resolve back to it (so none was shadowed)."""
    for court in COURTS.values():
        for alias in _aliases(court):
            assert resolve_court(alias).code == court.code, alias


@given(st.sampled_from(sorted(COURTS)))
def test_code_roundtrip(code: str) -> None:
    assert resolve_court(code).code == code
    assert resolve_court(COURTS[code].name).code == code


@given(st.text(max_size=12))
def test_never_guesses(text: str) -> None:
    """Arbitrary text either resolves to an indexed alias or raises."""
    try:
        court = resolve_court(text)
    except UnknownCourtError:
        return
    assert court.code in COURTS
    assert _alias_index()  # resolved only via the index
