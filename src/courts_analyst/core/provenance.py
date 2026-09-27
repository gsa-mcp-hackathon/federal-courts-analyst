"""Provenance: where every number came from.

Every figure the core returns carries a :class:`Provenance`: the table,
series and edition it was printed in (or that it was computed from the IDB),
the reporting period, the measure's definition, a link and cell reference,
and whether later editions revised it. Nothing leaves the core without one.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["official_table", "idb_derived", "derived"]
RevisionStatus = Literal["only_edition", "original", "revised"]
PeriodType = Literal["fiscal_year", "statistical_year"]
BadgeStatus = Literal[
    "matched", "explained_variance", "unexplained", "no_official_counterpart"
]

SERIES_TITLES = {
    "JB": "Judicial Business of the United States Courts",
    "JFF": "Judicial Facts and Figures",
}


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Period(_Model):
    """The 12-month period a figure covers."""

    fiscal_year: int = Field(description="Year the period ends in (FY2020 ends 2020).")
    period_end: date = Field(description="Last day of the period.")
    period_type: PeriodType = Field(
        description="'fiscal_year' (Oct 1–Sep 30) or 'statistical_year' (Jul 1–Jun 30, "
        "used for the 1990 rows)."
    )

    @classmethod
    def for_end(cls, fiscal_year: int, period_end: date) -> Period:
        kind: PeriodType = (
            "statistical_year"
            if (period_end.month, period_end.day) == (6, 30)
            else "fiscal_year"
        )
        return cls(fiscal_year=fiscal_year, period_end=period_end, period_type=kind)

    @classmethod
    def fiscal(cls, fiscal_year: int) -> Period:
        return cls(
            fiscal_year=fiscal_year,
            period_end=date(fiscal_year, 9, 30),
            period_type="fiscal_year",
        )


class FigureRef(_Model):
    """One published value of a figure in one edition."""

    value: float = Field(
        description="The value as printed (rounded to the table's precision)."
    )
    edition: str = Field(description="Edition id, for example JB-2020 or JFF-2023.")
    table_code: str = Field(description="Table, for example X-1A or 6.2.")
    url: str | None = Field(
        default=None, description="Published file the value was read from."
    )
    cell_ref: str | None = Field(
        default=None, description="Sheet!cell (xlsx) or page/line (PDF) of the value."
    )


class ReconciliationBadge(_Model):
    """How an IDB rebuild of a figure compares with the official table."""

    status: BadgeStatus
    official_value: float | None = None
    idb_value: float | None = None
    variance: float | None = Field(default=None, description="IDB minus official.")
    variance_pct: float | None = None
    explanation: str | None = None


class Provenance(_Model):
    """Where a number came from and how far to trust it."""

    source: SourceKind = Field(
        description="'official_table' (printed in a uscourts.gov table), 'idb_derived' "
        "(computed from FJC IDB records) or 'derived' (computed from official figures)."
    )
    table_code: str | None = None
    series: str | None = Field(default=None, description="Publication series title.")
    edition: str | None = None
    period: Period | None = None
    definition: str = Field(description="Plain-language definition of the measure.")
    url: str | None = None
    cell_ref: str | None = None
    revision_status: RevisionStatus | None = Field(
        default=None,
        description="'only_edition' (published once), 'original' (republished "
        "unchanged) or 'revised' (a later edition printed a different value).",
    )
    first_published: FigureRef | None = None
    later_revisions: list[FigureRef] = Field(
        default_factory=list,
        description="Every later edition whose value differs from the one before it.",
    )
    reconciliation: ReconciliationBadge | None = None
    dataset_release: str | None = Field(
        default=None, description="IDB release the figure was computed from."
    )
    note: str | None = None


def series_title(edition: str) -> str | None:
    return SERIES_TITLES.get(edition.split("-", 1)[0])
