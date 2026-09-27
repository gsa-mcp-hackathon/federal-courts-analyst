"""Why a figure differs between editions: the official history, and, only
where the district figures support it, our labelled inference.

The inference (for a national per-judgeship revision) is offered only when
one district's filings, in the first-published Judicial Business edition,
cover at least half of the revision **and** most of that district's filings
that year were directly filed MDL cases. It always carries an
``inferred_not_official`` warning: no published note explains these
revisions, so it stays an inference until the AO confirms (issue #8).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from courts_analyst.core.chain import Row, history_text
from courts_analyst.core.courts import COURTS
from courts_analyst.core.db import Database
from courts_analyst.core.measures import Measure
from courts_analyst.core.numbers import fmt
from courts_analyst.core.results import Caveat

INFERENCE_SHARE = 0.5
"""A district must cover this share of a revision before the inference is made."""


class RevisionNote(BaseModel):
    """One statement about why editions differ, labelled by what backs it."""

    basis: Literal["official", "inferred"]
    text: str
    district: str | None = Field(
        default=None, description="The district an inference is about."
    )
    points: float | None = Field(
        default=None,
        description="Points of the first-published figure that district contributes.",
    )
    revision: float | None = Field(
        default=None, description="Latest minus first-published value."
    )


def _name(code: str) -> str:
    c = COURTS.get(code)
    return (c.citation or c.name) if c else code


def mdl_dominated(db: Database, court: str, fy: int) -> bool:
    """Most of the district's filings that year were directly filed MDL cases."""
    if not db.has_idb:
        return False
    row = db.one(
        "SELECT avg(CAST(is_mdl_direct_filed AS INTEGER)) FROM idb.idb_civil "
        "WHERE court = ? AND filing_fy = ?",
        [court, fy],
    )
    return bool(row and row[0] is not None and row[0] >= 0.5)


def largest_district_share(
    db: Database, m: Measure, fy: int, edition: str
) -> tuple[str, float] | None:
    """(district, points of the national figure it contributes) in one edition."""
    rows = db.rows(
        "SELECT v.court, v.value * j.value FROM cat.observation v "
        "JOIN cat.observation j ON j.court = v.court AND j.fiscal_year = v.fiscal_year "
        "AND j.edition = v.edition AND j.measure_id = 'authorized_judgeships' "
        "WHERE v.measure_id = ? AND v.fiscal_year = ? AND v.edition = ? "
        "AND v.court NOT LIKE 'CIR-%' AND v.court <> 'US' ORDER BY 2 DESC LIMIT 1",
        [m.id, fy, edition],
    )
    national_j = db.one(
        "SELECT value FROM cat.observation WHERE measure_id = 'authorized_judgeships' "
        "AND court = 'US' AND fiscal_year = ? AND edition = ?",
        [fy, edition],
    )
    if not rows or not national_j or not national_j[0]:
        return None
    return str(rows[0][0]), float(rows[0][1]) / float(national_j[0])


def revision_notes(
    db: Database, m: Measure, court: str, fy: int, chain: list[Row]
) -> tuple[list[RevisionNote], list[Caveat]]:
    """Notes explaining a revised figure (empty when it wasn't revised)."""
    if len({r.shown for r in chain}) <= 1:
        return [], []
    first, latest = chain[0], chain[-1]
    revision = latest.shown - first.shown
    official = (
        "Judicial Business restates the prior year's closing pending count in the "
        "next edition's Table C-1."
        if m.id.endswith("pending")
        else "The tables' notes don't explain the change."
    )
    notes = [
        RevisionNote(
            basis="official",
            text=f"FY{fy} {m.label}: {history_text(chain)}. {official}",
            revision=revision,
        )
    ]
    warnings: list[Caveat] = []
    if m.family == "per_judgeship" and court == "US" and first.edition.startswith("JB"):
        top = largest_district_share(db, m, fy, first.edition)
        if (
            top
            and top[1] >= INFERENCE_SHARE * abs(revision)
            and mdl_dominated(db, top[0], fy)
        ):
            code, points = top
            notes.append(
                RevisionNote(
                    basis="inferred",
                    text=(
                        f"In {first.edition} Table X-1A, {_name(code)}'s filings "
                        f"contribute {points:.0f} points to the national "
                        f"{fmt(first.shown)}; the later edition's figure is "
                        f"{abs(revision):.0f} points lower. That is consistent with "
                        "the revised series excluding or down-weighting those cases "
                        "(mostly directly filed MDL cases), but no published note "
                        "says so. Unconfirmed: needs AO confirmation."
                    ),
                    district=code,
                    points=points,
                    revision=revision,
                )
            )
            warnings.append(
                Caveat(
                    code="inferred_not_official",
                    message=(
                        f"The explanation of the FY{fy} revision is our inference "
                        "from the district figures, not an official statement."
                    ),
                )
            )
    return notes, warnings
