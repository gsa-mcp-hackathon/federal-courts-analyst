"""Closed vocabularies for inputs: courts, measures, editions, cohort fields.

Each is a ``str`` constrained to a fixed set of values, and its JSON schema is
an ``enum``, so an MCP client sees every allowed value and a model can't
invent one ("SDNY", "JB2020"). The value sets come from the registries they
describe (``core.courts``, ``core/data/measures.yaml``, the IDB codebook), so
they can't drift from the data.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Annotated, Any, Final

import yaml
from pydantic import AfterValidator, WithJsonSchema

from courts_analyst.core.courts import COURTS, CourtLevel

EDITIONS: Final[tuple[str, ...]] = tuple(
    f"{series}-{year}" for year in range(2016, 2026) for series in ("JB", "JFF")
)
"""Every edition in the catalog, in publication order (JB before JFF each year).
``tests/test_enums.py`` checks this against ``data/manifest/tables.yaml``."""

EDITION_ALIASES: Final[tuple[str, ...]] = ("latest", "first_published")


def closed_str(values: Iterable[str], what: str, description: str) -> Any:
    allowed = tuple(values)
    allowed_set = frozenset(allowed)

    def check(v: str) -> str:
        if v not in allowed_set:
            raise ValueError(f"unknown {what} {v!r}")
        return v

    return Annotated[
        str,
        AfterValidator(check),
        WithJsonSchema(
            {"type": "string", "enum": list(allowed), "description": description}
        ),
    ]


COURT_CODES: Final[tuple[str, ...]] = tuple(COURTS)
DISTRICT_CODES: Final[tuple[str, ...]] = tuple(
    c for c, v in COURTS.items() if v.level is CourtLevel.DISTRICT
)

_CourtCode = closed_str(
    COURT_CODES,
    "court",
    "Court code: US (all district courts), a circuit (CIR-01 … CIR-11, CIR-DC) "
    "or a district (state postal code, plus -N/-E/-S/-W/-M/-C for divided "
    "states: FL-N = N.D. Fla., NY-S = S.D.N.Y., DC = D.D.C.).",
)


@cache
def _measures_yaml() -> dict[str, dict[str, Any]]:
    text = resources.files("courts_analyst.core").joinpath("data/measures.yaml")
    data: dict[str, dict[str, Any]] = yaml.safe_load(text.read_text())
    return data


MEASURE_IDS: Final[tuple[str, ...]] = tuple(_measures_yaml())

_MeasureId = closed_str(
    MEASURE_IDS,
    "measure",
    "A published statistic (see courts://glossary or explain_term for definitions).",
)

_EditionId = closed_str(
    EDITIONS,
    "edition",
    "A publication: JB-<year> (Judicial Business, first publication of that "
    "fiscal year) or JFF-<year> (Judicial Facts and Figures, which repeats and "
    "sometimes revises earlier years).",
)

_EditionSelector = closed_str(
    (*EDITION_ALIASES, *EDITIONS),
    "edition",
    "Which edition's figure to return: 'latest' (default: the current official "
    "figure), 'first_published', or a specific edition such as JB-2020 or JFF-2023.",
)


@cache
def _codebook(field: str) -> list[dict[str, Any]]:
    text = resources.files("courts_analyst.pipeline.idb").joinpath(
        f"codebook/{field}.yaml"
    )
    codes: list[dict[str, Any]] = yaml.safe_load(text.read_text())["codes"]
    return codes


def _distinct(field: str, key: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for c in _codebook(field):
        if c.get(key):
            seen.setdefault(str(c[key]), None)
    return tuple(seen)


NOS_CODES: Final[tuple[str, ...]] = tuple(str(c["code"]) for c in _codebook("nos"))
NOS_GROUPS: Final[tuple[str, ...]] = _distinct("nos", "group")
NOS_CATEGORIES: Final[tuple[str, ...]] = _distinct("nos", "category")
ORIGIN_GROUPS: Final[tuple[str, ...]] = _distinct("origin", "group")
JURISDICTION_GROUPS: Final[tuple[str, ...]] = _distinct("juris", "group")
DISPOSITION_GROUPS: Final[tuple[str, ...]] = _distinct("disp", "group")
PRO_SE_GROUPS: Final[tuple[str, ...]] = _distinct("prose", "group")

_NosCode = closed_str(
    NOS_CODES, "nature-of-suit code", "Three-digit nature-of-suit code."
)
_NosGroup = closed_str(
    NOS_GROUPS, "nature-of-suit group", "Table C-2 nature-of-suit group."
)
_NosCategory = closed_str(
    NOS_CATEGORIES, "nature-of-suit category", "Table C-2 top-level category."
)
_OriginGroup = closed_str(
    ORIGIN_GROUPS,
    "origin",
    "How the case arrived: original, removed, remanded, reopened, transferred, "
    "mdl_transfer (sent by the JPML), mdl_direct (filed directly in the MDL "
    "court, from July 2016), appeal_from_magistrate.",
)
_JurisdictionGroup = closed_str(
    JURISDICTION_GROUPS, "jurisdiction", "us (U.S. a party) or private."
)
_DispositionGroup = closed_str(
    DISPOSITION_GROUPS,
    "disposition",
    "dismissed, judgment (including settlements entered as judgments and "
    "statistical closings) or transferred_or_remanded.",
)
_ProSeGroup = closed_str(
    PRO_SE_GROUPS,
    "pro se",
    "Who was pro se at filing: plaintiff, defendant, both, none.",
)


# Type checkers see plain ``str``; at runtime each alias is the constrained,
# enum-schema'd ``Annotated[str, ...]`` built above.
if TYPE_CHECKING:
    CourtCode = str
    MeasureId = str
    EditionId = str
    EditionSelector = str
    NosCode = str
    NosGroup = str
    NosCategory = str
    OriginGroup = str
    JurisdictionGroup = str
    DispositionGroup = str
    ProSeGroup = str
else:
    CourtCode = _CourtCode
    MeasureId = _MeasureId
    EditionId = _EditionId
    EditionSelector = _EditionSelector
    NosCode = _NosCode
    NosGroup = _NosGroup
    NosCategory = _NosCategory
    OriginGroup = _OriginGroup
    JurisdictionGroup = _JurisdictionGroup
    DispositionGroup = _DispositionGroup
    ProSeGroup = _ProSeGroup


def label_lookup(field: str) -> Callable[[str], str | None]:
    """Code → label for a codebook field (``nos``, ``origin``, …)."""
    table = {str(c["code"]): str(c["label"]) for c in _codebook(field)}
    return table.get


def nos_entry(code: str) -> dict[str, Any] | None:
    """The codebook entry for a nature-of-suit code, or None."""
    return next((c for c in _codebook("nos") if str(c["code"]) == code), None)
