"""Canonical registry of federal courts: 94 districts, 12 circuits, national.

Every figure in the catalog is keyed by a canonical court code (``FL-N``,
``DC``, ``CIR-11``, ``US``). The official tables name courts in several ways
("FL,N", "Florida, Northern", "N.D. Fla."); :func:`resolve_court` maps all of
them to one code and raises :class:`UnknownCourtError` rather than guessing.

Pure domain logic: no I/O, no MCP or HTTP imports (ADR 0002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Final

from courts_analyst.core.errors import UnknownCourtError

__all__ = [
    "CIRCUITS",
    "COURTS",
    "DISTRICTS",
    "TERRITORIAL",
    "Court",
    "CourtLevel",
    "UnknownCourtError",
    "court_aliases",
    "normalize_court_text",
    "resolve_court",
]


class CourtLevel(StrEnum):
    """What kind of unit a court code refers to."""

    NATIONAL = "national"
    CIRCUIT = "circuit"
    DISTRICT = "district"


@dataclass(frozen=True, slots=True)
class Court:
    """One court (or aggregate) that figures can be reported for."""

    code: str
    """Canonical code, for example ``FL-N``, ``CIR-11`` or ``US``."""
    name: str
    """Plain-language name, for example ``Florida, Northern``."""
    level: CourtLevel
    circuit: str | None
    """Circuit code (``CIR-11``) for districts; ``None`` otherwise."""
    citation: str | None = None
    """Bluebook form for districts, for example ``N.D. Fla.``."""
    state: str | None = None
    """Two-letter postal code for districts."""
    division: str | None = None
    """``N``/``E``/``S``/``W``/``M``/``C`` for multi-district states."""


# (postal, full state name, Bluebook abbreviation)
_STATES: Final[dict[str, tuple[str, str]]] = {
    "AL": ("Alabama", "Ala."),
    "AK": ("Alaska", "Alaska"),
    "AZ": ("Arizona", "Ariz."),
    "AR": ("Arkansas", "Ark."),
    "CA": ("California", "Cal."),
    "CO": ("Colorado", "Colo."),
    "CT": ("Connecticut", "Conn."),
    "DE": ("Delaware", "Del."),
    "DC": ("District of Columbia", "D.C."),
    "FL": ("Florida", "Fla."),
    "GA": ("Georgia", "Ga."),
    "GU": ("Guam", "Guam"),
    "HI": ("Hawaii", "Haw."),
    "ID": ("Idaho", "Idaho"),
    "IL": ("Illinois", "Ill."),
    "IN": ("Indiana", "Ind."),
    "IA": ("Iowa", "Iowa"),
    "KS": ("Kansas", "Kan."),
    "KY": ("Kentucky", "Ky."),
    "LA": ("Louisiana", "La."),
    "ME": ("Maine", "Me."),
    "MD": ("Maryland", "Md."),
    "MA": ("Massachusetts", "Mass."),
    "MI": ("Michigan", "Mich."),
    "MN": ("Minnesota", "Minn."),
    "MS": ("Mississippi", "Miss."),
    "MO": ("Missouri", "Mo."),
    "MT": ("Montana", "Mont."),
    "NE": ("Nebraska", "Neb."),
    "NV": ("Nevada", "Nev."),
    "NH": ("New Hampshire", "N.H."),
    "NJ": ("New Jersey", "N.J."),
    "NM": ("New Mexico", "N.M."),
    "NY": ("New York", "N.Y."),
    "NC": ("North Carolina", "N.C."),
    "ND": ("North Dakota", "N.D."),
    "MP": ("Northern Mariana Islands", "N. Mar. I."),
    "OH": ("Ohio", "Ohio"),
    "OK": ("Oklahoma", "Okla."),
    "OR": ("Oregon", "Or."),
    "PA": ("Pennsylvania", "Pa."),
    "PR": ("Puerto Rico", "P.R."),
    "RI": ("Rhode Island", "R.I."),
    "SC": ("South Carolina", "S.C."),
    "SD": ("South Dakota", "S.D."),
    "TN": ("Tennessee", "Tenn."),
    "TX": ("Texas", "Tex."),
    "UT": ("Utah", "Utah"),
    "VT": ("Vermont", "Vt."),
    "VI": ("Virgin Islands", "V.I."),
    "VA": ("Virginia", "Va."),
    "WA": ("Washington", "Wash."),
    "WV": ("West Virginia", "W. Va."),
    "WI": ("Wisconsin", "Wis."),
    "WY": ("Wyoming", "Wyo."),
}

_DIVISIONS: Final[dict[str, str]] = {
    "N": "Northern",
    "E": "Eastern",
    "S": "Southern",
    "W": "Western",
    "M": "Middle",
    "C": "Central",
}

# Districts in the AO's table order, grouped by circuit. "XX" = single-district
# state; "XX-N" etc. = one district of a multi-district state.
_CIRCUIT_DISTRICTS: Final[dict[str, tuple[str, ...]]] = {
    "CIR-DC": ("DC",),
    "CIR-01": ("ME", "MA", "NH", "RI", "PR"),
    "CIR-02": ("CT", "NY-N", "NY-E", "NY-S", "NY-W", "VT"),
    "CIR-03": ("DE", "NJ", "PA-E", "PA-M", "PA-W", "VI"),
    "CIR-04": ("MD", "NC-E", "NC-M", "NC-W", "SC", "VA-E", "VA-W", "WV-N", "WV-S"),
    "CIR-05": ("LA-E", "LA-M", "LA-W", "MS-N", "MS-S", "TX-N", "TX-E", "TX-S", "TX-W"),
    "CIR-06": ("KY-E", "KY-W", "MI-E", "MI-W", "OH-N", "OH-S", "TN-E", "TN-M", "TN-W"),
    "CIR-07": ("IL-N", "IL-C", "IL-S", "IN-N", "IN-S", "WI-E", "WI-W"),
    "CIR-08": (
        "AR-E",
        "AR-W",
        "IA-N",
        "IA-S",
        "MN",
        "MO-E",
        "MO-W",
        "NE",
        "ND",
        "SD",
    ),
    "CIR-09": (
        "AK",
        "AZ",
        "CA-N",
        "CA-E",
        "CA-C",
        "CA-S",
        "HI",
        "ID",
        "MT",
        "NV",
        "OR",
        "WA-E",
        "WA-W",
        "GU",
        "MP",
    ),
    "CIR-10": ("CO", "KS", "NM", "OK-N", "OK-E", "OK-W", "UT", "WY"),
    "CIR-11": ("AL-N", "AL-M", "AL-S", "FL-N", "FL-M", "FL-S", "GA-N", "GA-M", "GA-S"),
}

TERRITORIAL: Final[frozenset[str]] = frozenset({"VI", "GU", "MP"})
"""Territorial (Article IV) district courts. Several judgeship tables omit them."""


_INITIALS: Final = re.compile(r"(?:[A-Z]\.)+")


def _ordinal(n: int) -> str:
    suffix = (
        "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    )
    return f"{n}{suffix}"


def _circuit_name(code: str) -> str:
    return "DC Circuit" if code == "CIR-DC" else f"{_ordinal(int(code[4:]))} Circuit"


def _district(code: str, circuit: str) -> Court:
    state, _, div = code.partition("-")
    state_name, abbr = _STATES[state]
    if div:
        name = f"{state_name}, {_DIVISIONS[div]}"
        sep = "" if _INITIALS.fullmatch(abbr) else " "
        citation = f"{div}.D.{sep}{abbr}"
    else:
        name = state_name
        # Bluebook joins "D." to an abbreviation that starts with a capital
        # initial ("D.D.C.", "D.P.R.") and spaces it before words ("D. Mass.").
        citation = f"D.{abbr}" if _INITIALS.fullmatch(abbr) else f"D. {abbr}"
    return Court(
        code=code,
        name=name,
        level=CourtLevel.DISTRICT,
        circuit=circuit,
        citation=citation,
        state=state,
        division=div or None,
    )


def _build_registry() -> dict[str, Court]:
    courts: dict[str, Court] = {
        "US": Court("US", "All district courts", CourtLevel.NATIONAL, None)
    }
    for cir, districts in _CIRCUIT_DISTRICTS.items():
        courts[cir] = Court(cir, _circuit_name(cir), CourtLevel.CIRCUIT, None)
        for d in districts:
            courts[d] = _district(d, cir)
    return courts


COURTS: Final[dict[str, Court]] = _build_registry()
"""Every known court by canonical code, in AO table order."""

DISTRICTS: Final[tuple[str, ...]] = tuple(
    c.code for c in COURTS.values() if c.level is CourtLevel.DISTRICT
)
CIRCUITS: Final[tuple[str, ...]] = tuple(_CIRCUIT_DISTRICTS)


def _norm(text: str) -> str:
    """Collapse case, punctuation and filler so aliases compare equal."""
    t = text.upper().replace("&", " AND ")
    t = re.sub(r"\bDISTRICT OF\b|\bDISTRICT\b|\bDIST\b|\bCOURT\b|\bTHE\b", " ", t)
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return " ".join(t.split())


def _aliases(court: Court) -> set[str]:
    out = {court.code, court.name}
    if court.level is CourtLevel.NATIONAL:
        out |= {"National", "Total", "All Districts", "Total All Districts", "U.S."}
        out |= {"United States", "Total District Courts", "All District Courts"}
        return out
    if court.level is CourtLevel.CIRCUIT:
        n = court.code[4:]
        if n == "DC":
            out |= {
                "D.C. Circuit",
                "DC Cir",
                "D.C. Cir.",
                "District of Columbia Circuit",
            }
        else:
            i = int(n)
            # AO tables label circuit subtotal rows "1st", "2nd" … (or "1ST").
            out |= {_ordinal(i), f"{_ordinal(i)} Cir.", f"{_ordinal(i)} Circuit"}
            out.add(f"Circuit {i}")
            words = [
                "First", "Second", "Third", "Fourth", "Fifth", "Sixth",
                "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh",
            ]  # fmt: skip
            out |= {f"{words[i - 1]} Circuit", f"{i} Cir"}
        return out
    assert court.state is not None
    state_name, _ = _STATES[court.state]
    out.add(court.citation or "")
    if court.division:
        d, dname = court.division, _DIVISIONS[court.division]
        s = court.state
        out |= {
            f"{s},{d}",
            f"{s} {d}",
            f"{s}{d}",
            f"{d}.D. {state_name}",
            f"{dname} District of {state_name}",
            f"{state_name} {dname}",
            f"{dname} {state_name}",
            f"{state_name} - {dname}",
        }
    else:
        out |= {f"District of {state_name}", f"D. {state_name}"}
        if court.state == "MP":
            out |= {"Northern Mariana Islands", "NMI", "N. Mariana Islands", "D.N.M.I."}
    return out


@cache
def _alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for court in COURTS.values():
        for alias in _aliases(court):
            key = _norm(alias)
            if not key:
                continue
            prior = index.get(key)
            if prior is not None and prior != court.code:
                # Two courts share a spelling: never let either win silently.
                index[key] = ""
            else:
                index[key] = court.code
    return index


def resolve_court(name: str) -> Court:
    """Map any known spelling of a court to its canonical :class:`Court`.

    Accepts canonical codes (``FL-N``), AO table labels (``FL,N``), full names
    (``Florida, Northern``), Bluebook citations (``N.D. Fla.``) and circuit
    names (``11th Circuit``). Raises :class:`UnknownCourtError` for anything
    it can't match to exactly one court; it never guesses.
    """
    key = _norm(name)
    code = _alias_index().get(key)
    if not code:
        raise UnknownCourtError(f"Unknown or ambiguous court name: {name!r}")
    return COURTS[code]


def court_aliases(code: str) -> frozenset[str]:
    """Every spelling of the court ``code`` that :func:`resolve_court` accepts,
    normalised (upper case, punctuation collapsed to single spaces).

    Spellings two courts share are left out, as in :func:`resolve_court`.
    """
    index = _alias_index()
    return frozenset(
        key for alias in _aliases(COURTS[code]) if index.get(key := _norm(alias))
    )


def normalize_court_text(text: str) -> str:
    """Normalise free text the way court aliases are, for substring search."""
    return _norm(text)
