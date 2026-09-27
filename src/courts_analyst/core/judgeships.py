"""judgeship_context: a court's official weighted caseload next to the
Judicial Conference's published thresholds and recommendations.

Every fact carries its source. The module compares numbers with thresholds
("above 430") and reports what the Conference itself recommended; it never
recommends anything, and it doesn't claim a judicial emergency (that needs
vacancy data the server doesn't have).
"""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any

import yaml
from pydantic import BaseModel, Field

from courts_analyst.core.courts import COURTS, TERRITORIAL, CourtLevel
from courts_analyst.core.db import Database
from courts_analyst.core.errors import NotPublishedError, OutOfScopeError
from courts_analyst.core.guardrails import guarded
from courts_analyst.core.guardrails.policy import config
from courts_analyst.core.official import get_official_figure
from courts_analyst.core.provenance import FigureRef, Provenance
from courts_analyst.core.results import Caveat, Result, ok

PRIMARY = "weighted_total_filings_per_judgeship"


@cache
def reference() -> dict[str, Any]:
    text = resources.files("courts_analyst.core").joinpath("data/judgeships.yaml")
    data: dict[str, Any] = yaml.safe_load(text.read_text())
    return data


class Threshold(BaseModel):
    id: str
    value: float
    label: str
    description: str
    source: str
    url: str
    court_value: float = Field(description="The court's figure it is compared with.")
    above: bool
    margin: float = Field(description="court_value − value.")


class Recommendation(BaseModel):
    edition: str
    date: str
    current_authorized: float
    recommended_additional: float
    source: str
    url: str


class JudgeshipContext(BaseModel):
    court: str
    court_name: str
    fiscal_year: int
    weighted_total: FigureRef
    weighted_civil: FigureRef | None
    authorized_judgeships: FigureRef | None
    national_weighted_total: FigureRef | None = Field(
        description="The national figure from the same edition, for comparison."
    )
    thresholds: list[Threshold]
    recommendation: Recommendation | None = Field(
        description="The Judicial Conference's latest recommendation for this court, "
        "if it made one; None means none is recorded here."
    )
    statement: str = Field(description="A neutral, sourced summary sentence.")


def _latest_year(db: Database, court: str) -> int:
    row = db.one(
        "SELECT max(fiscal_year) FROM cat.observation "
        "WHERE measure_id = ? AND court = ?",
        [PRIMARY, court],
    )
    if not row or row[0] is None:
        raise NotPublishedError(
            f"No weighted filings are published for {court}.", ["compare_courts"]
        )
    return int(row[0])


@guarded
def judgeship_context(
    db: Database, court: str, fiscal_year: int | None = None
) -> Result[JudgeshipContext]:
    """Official weighted filings for ``court`` against the Conference's
    thresholds, plus its latest recommendation for the court."""
    c = COURTS.get(court)
    if c is None or c.level is CourtLevel.CIRCUIT:
        raise OutOfScopeError(
            "judgeship_context works for one district court or the nation (US).",
            ["compare_courts to rank a circuit's districts"],
        )
    if court in TERRITORIAL:
        raise NotPublishedError(
            f"{c.name} is a territorial court: it is outside the FJC case-weight "
            "studies, so no weighted filings are published for it.",
        )
    fy = fiscal_year or _latest_year(db, court)
    # District values exist only in the first-published Judicial Business
    # edition; use it for every figure so they come from one table.
    total = get_official_figure(db, PRIMARY, court, fy, "first_published")
    assert total.data is not None
    edition = total.data.edition
    warnings: list[Caveat] = list(total.warnings)

    def same_edition(measure: str, where: str) -> FigureRef | None:
        try:
            r = get_official_figure(db, measure, where, fy, edition)
        except Exception:  # not printed in this edition
            return None
        return (
            r.data.first_published.model_copy(
                update={"value": r.data.value, "edition": r.data.edition}
            )
            if r.data
            else None
        )

    ref = reference()
    thresholds = [
        Threshold(
            id=t["id"],
            value=float(t["value"]),
            label=t["label"],
            description=" ".join(str(t["description"]).split()),
            source=" ".join(str(t["source"]).split()),
            url=t["url"],
            court_value=total.data.value,
            above=total.data.value > float(t["value"]),
            margin=total.data.value - float(t["value"]),
        )
        for t in ref["thresholds"]
    ]
    rec = None
    for r in ref["recommendations"]:
        if court in r["districts"]:
            current, add = r["districts"][court]
            rec = Recommendation(
                edition=r["edition"],
                date=str(r["date"]),
                current_authorized=float(current),
                recommended_additional=float(add),
                source=r["title"],
                url=r["url"],
            )
            break
    name = c.citation or c.name
    parts = [
        f"{name} had {total.data.value:,.0f} weighted filings per authorized "
        f"judgeship in FY{fy} ({edition}, Table {total.data.table_code}),"
    ]
    above = [t for t in thresholds if t.above]
    if total.data.latest.value != total.data.value:
        parts[-1] += (
            f" later revised to {total.data.latest.value:,.0f} in "
            f"{total.data.latest.edition},"
        )
    if above:
        plural = "s" if len(above) > 1 else ""
        parts.append(
            "above the "
            + " and ".join(f"{t.value:g}" for t in above)
            + f" threshold{plural}."
        )
    else:
        parts.append(f"below the {thresholds[0].value:g} standard.")
    if rec:
        parts.append(
            f"In {rec.date[:4]} the Judicial Conference recommended "
            f"{rec.recommended_additional:g} additional judgeship"
            f"{'s' if rec.recommended_additional != 1 else ''} for it."
        )
    elif court != "US":
        parts.append(
            "The Judicial Conference's 2025 recommendations include no new "
            "judgeship for it."
        )
    parts.append("This server makes no recommendation of its own.")
    data = JudgeshipContext(
        court=court,
        court_name=name,
        fiscal_year=fy,
        weighted_total=total.data.first_published.model_copy(
            update={"value": total.data.value, "edition": edition}
        ),
        weighted_civil=same_edition("weighted_civil_filings_per_judgeship", court),
        authorized_judgeships=same_edition("authorized_judgeships", court),
        national_weighted_total=same_edition(PRIMARY, "US") if court != "US" else None,
        thresholds=thresholds,
        recommendation=rec,
        statement=" ".join(parts),
    )
    prov = list(total.provenance)
    if rec:
        prov.append(
            Provenance(
                source="official_table",
                table_code="JC recommendations Table 1",
                series="Judicial Conference of the United States",
                edition=rec.edition,
                definition="Additional judgeships recommended by the Judicial "
                "Conference.",
                url=rec.url,
            )
        )
    warnings.append(
        Caveat(
            code="out_of_scope",
            severity="info",
            message="Judicial emergency status depends on vacancies, which this "
            "server doesn't track; see the thresholds' descriptions.",
        )
    )
    warnings.append(
        Caveat(
            code="no_recommendation",
            severity="info",
            message=" ".join(config()["policies"]["advocacy"]["message"].split())
            + " Report these facts; don't lay out a case for or against.",
        )
    )
    return ok(data, prov, warnings)
