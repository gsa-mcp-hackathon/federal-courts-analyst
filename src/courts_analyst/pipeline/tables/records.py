"""Typed rows produced by the table parsers and loaded into DuckDB.

``edition`` is the publication (``JB-2020``, ``JFF-2023``), not the data year:
JFF-2023 Table 6.2 reports FY2019–FY2023, so one edition holds figures for
many fiscal years, and one fiscal year appears in many editions.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Series(StrEnum):
    """Publication series on uscourts.gov."""

    JB = "JB"
    """Judicial Business of the U.S. Courts (12 months ending Sep 30)."""
    JFF = "JFF"
    """Judicial Facts and Figures (multi-year series, Sep 30)."""
    STFJ = "STFJ"
    """Statistical Tables for the Federal Judiciary (Jun 30 and Dec 31)."""
    FJCS = "FJCS"
    """Federal Judicial Caseload Statistics (Mar 31)."""
    FCMS = "FCMS"
    """Federal Court Management Statistics (district profiles)."""


SERIES_TITLES: dict[Series, str] = {
    Series.JB: "Judicial Business of the United States Courts",
    Series.JFF: "Judicial Facts and Figures",
    Series.STFJ: "Statistical Tables for the Federal Judiciary",
    Series.FJCS: "Federal Judicial Caseload Statistics",
    Series.FCMS: "Federal Court Management Statistics",
}

SERIES_SLUGS: dict[Series, str] = {
    Series.JB: "judicial-business",
    Series.JFF: "judicial-facts-and-figures",
    Series.STFJ: "statistical-tables-federal-judiciary",
    Series.FJCS: "federal-judicial-caseload-statistics",
    Series.FCMS: "federal-court-management-statistics",
}


def edition_id(series: Series, period_end: date) -> str:
    """``JB-2020`` for Sep 30 series; ``STFJ-2024-06`` when the month matters."""
    if series in (Series.JB, Series.JFF) or period_end.month == 9:
        return f"{series.value}-{period_end.year}"
    return f"{series.value}-{period_end.year}-{period_end.month:02d}"


_EDITION = re.compile(r"^(JB|JFF|STFJ|FJCS|FCMS)-\d{4}(-\d{2})?$")


class SourceFile(BaseModel):
    """One downloaded file (a table in one edition and one format)."""

    model_config = ConfigDict(frozen=True)

    file_id: str = Field(description="Stable id: '<edition>:<table>:<format>'.")
    url: str
    landing_url: str | None = None
    sha256: str
    fetched_at: str | None = None
    series: Series
    table_code: str = Field(description="Table code as published, e.g. 'X-1A', '6.2'.")
    edition: str
    period_end: date
    format: str = Field(pattern=r"^(xlsx|pdf)$")
    title: str | None = None

    @field_validator("edition")
    @classmethod
    def _edition_shape(cls, v: str) -> str:
        if not _EDITION.match(v):
            raise ValueError(f"bad edition id {v!r}")
        return v


class Footnote(BaseModel):
    """A note printed with a table. ``marker`` is the symbol used in cells."""

    model_config = ConfigDict(frozen=True)

    footnote_id: str
    file_id: str
    marker: str | None
    text: str


class Observation(BaseModel):
    """One published number: a measure, for a court and year, in one edition."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    measure_id: str
    court: str = Field(description="Canonical court code from core.courts.")
    fiscal_year: int = Field(ge=1980, le=2100)
    period_end: date
    value: float | None = Field(description="None when the table prints a dash/NA.")
    decimals: int | None = Field(
        default=None,
        description="Decimal places as displayed; revisions compare at this precision.",
    )
    footnote_ids: tuple[str, ...] = ()
    cell_ref: str = Field(
        description="Where the number is: 'Sheet!B12' (xlsx) or 'p1:line12:col3' (PDF)."
    )
    raw: str | None = Field(default=None, description="The cell text as printed.")
