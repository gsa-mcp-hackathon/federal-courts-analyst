"""The measures registry: what each published statistic means and where it lives.

Loaded from ``core/data/measures.yaml``, the same file the tables pipeline
uses to label observations, so a measure's definition can't differ between
the catalog and the server. The official tables are authoritative for every
measure; ``idb`` names the rule that rebuilds a count from IDB records, used
only to reconcile and decompose.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml

from courts_analyst.core.errors import UnknownMeasureError

IdbRule = Literal["filed", "terminated", "pending"]
Family = Literal["per_judgeship", "count", "median_months", "judgeships"]

MEASURES_RESOURCE = "data/measures.yaml"

# Pending on date D (moved here from pipeline/idb/profile.py, Phase 2): filed
# (AO date) by D, not terminated by D, and, for a repeat record, its previous
# termination on or before D (the IDB doesn't record reopening dates).
PENDING_WHERE = (
    "filing_date_ao <= ? AND (termination_date_ao IS NULL OR termination_date_ao > ?)"
    " AND (prev_termination_date_ao IS NULL OR prev_termination_date_ao <= ?)"
)


@dataclass(frozen=True, slots=True)
class Measure:
    id: str
    label: str
    definition: str
    unit: str
    weighted: bool
    denominator: str | None
    decimals: int
    tables: tuple[str, ...]
    idb: IdbRule | None

    @property
    def family(self) -> Family:
        if self.id.startswith("authorized_judgeships"):
            return "judgeships"
        if self.denominator == "authorized_judgeships":
            return "per_judgeship"
        if "median" in self.id:
            return "median_months"
        return "count"


def _measure(mid: str, raw: dict[str, Any]) -> Measure:
    return Measure(
        id=mid,
        label=str(raw["label"]),
        definition=" ".join(str(raw["definition"]).split()),
        unit=str(raw["unit"]),
        weighted=bool(raw["weighted"]),
        denominator=raw.get("denominator"),
        decimals=int(raw["decimals"]),
        tables=tuple(str(t) for t in raw.get("tables", [])),
        idb=raw.get("idb"),
    )


@cache
def registry() -> dict[str, Measure]:
    text = resources.files("courts_analyst.core").joinpath(MEASURES_RESOURCE)
    data: dict[str, dict[str, Any]] = yaml.safe_load(text.read_text())
    return {mid: _measure(mid, raw) for mid, raw in data.items()}


def get_measure(measure_id: str) -> Measure:
    try:
        return registry()[measure_id]
    except KeyError:
        close = [m for m in registry() if measure_id.lower() in m][:5]
        raise UnknownMeasureError(
            f"Unknown measure {measure_id!r}.",
            [f"try one of: {', '.join(close)}"] if close else ["call explain_term"],
        ) from None


def idb_measures() -> dict[str, Measure]:
    """Measures the IDB can rebuild (for reconcile and explain_change)."""
    return {k: m for k, m in registry().items() if m.idb}
