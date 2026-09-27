"""Official figures: one published statistic, every edition of it, and
cross-court comparisons that never mix editions.

Default edition policy (ADR 0004): return the **latest** edition's value and
always attach the first-published value and every revision in between, so
the 554 → 322 story is visible without anyone having to ask for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, Field

from courts_analyst.core.courts import COURTS, TERRITORIAL, CourtLevel
from courts_analyst.core.db import Database
from courts_analyst.core.enums import EDITIONS
from courts_analyst.core.errors import (
    NotPublishedError,
    OutOfScopeError,
    UnknownCourtError,
    UnknownEditionError,
)
from courts_analyst.core.measures import Measure, get_measure
from courts_analyst.core.numbers import fmt, round_half_up
from courts_analyst.core.provenance import (
    FigureRef,
    Period,
    Provenance,
    RevisionStatus,
    series_title,
)
from courts_analyst.core.results import Caveat, Result, ok

CHAIN_SQL = """
SELECT o.edition, o.table_code, o.value, o.decimals, e.pub_order, o.cell_ref,
       s.url, o.period_end, o.footnote_ids
FROM cat.observation o
JOIN cat.edition e USING (edition)
JOIN cat.source_file s USING (file_id)
WHERE o.measure_id = ? AND o.court = ? AND o.fiscal_year = ? AND o.value IS NOT NULL
ORDER BY e.pub_order
"""

YEARS_SQL = """
SELECT DISTINCT fiscal_year FROM cat.observation
WHERE measure_id = ? AND court = ? AND value IS NOT NULL ORDER BY 1
"""

FOOTNOTES_SQL = "SELECT text FROM cat.footnote WHERE list_contains(?, footnote_id)"

EDITION_ROWS_SQL = """
SELECT o.edition, e.pub_order, count(*) AS n
FROM cat.observation o JOIN cat.edition e USING (edition)
WHERE o.measure_id = ? AND o.fiscal_year = ? AND o.value IS NOT NULL
  AND list_contains(?, o.court)
GROUP BY ALL ORDER BY e.pub_order DESC
"""

COMPARE_SQL = """
SELECT o.court, o.value, o.decimals, o.cell_ref, o.table_code, s.url, o.period_end
FROM cat.observation o JOIN cat.source_file s USING (file_id)
WHERE o.measure_id = ? AND o.fiscal_year = ? AND o.edition = ? AND o.value IS NOT NULL
  AND list_contains(?, o.court)
"""


@dataclass(frozen=True)
class _Row:
    edition: str
    table_code: str
    value: float
    decimals: int
    pub_order: int
    cell_ref: str | None
    url: str | None
    period_end: date
    footnote_ids: list[str]

    @property
    def shown(self) -> float:
        return round_half_up(self.value, self.decimals)

    def ref(self) -> FigureRef:
        return FigureRef(
            value=self.shown,
            edition=self.edition,
            table_code=self.table_code,
            url=self.url,
            cell_ref=self.cell_ref,
        )


class OfficialFigure(BaseModel):
    """A published statistic in one edition, with its full edition history."""

    measure: str
    measure_label: str
    unit: str
    court: str
    court_name: str
    fiscal_year: int
    value: float = Field(description="The value as printed in `edition`.")
    edition: str
    table_code: str
    period: Period
    revision_status: RevisionStatus
    first_published: FigureRef
    latest: FigureRef
    editions: list[FigureRef] = Field(
        description="Every edition that printed this figure, oldest first."
    )
    footnotes: list[str] = Field(default_factory=list)


class CourtRow(BaseModel):
    rank: int
    court: str
    court_name: str
    citation: str | None
    value: float
    cell_ref: str | None


class CourtComparison(BaseModel):
    """Courts ranked on one measure, all from the same edition."""

    measure: str
    measure_label: str
    unit: str
    fiscal_year: int
    edition: str
    table_code: str
    order: Literal["desc", "asc"]
    rows: list[CourtRow]
    national: FigureRef | None = Field(
        default=None, description="The national figure from the same edition."
    )
    national_latest: FigureRef | None = Field(
        default=None,
        description="The national figure in the latest edition, when it differs.",
    )
    not_published: list[str] = Field(
        default_factory=list,
        description="Requested courts the edition prints no value for.",
    )
    total_courts: int


def _check_court(court: str) -> None:
    if court not in COURTS:
        raise UnknownCourtError(f"Unknown court code {court!r}.", ["explain_term"])


def _chain(db: Database, measure: str, court: str, fy: int) -> list[_Row]:
    return [
        _Row(e, t, v, d if d is not None else 0, p, c, u, pe, list(f or []))
        for e, t, v, d, p, c, u, pe, f in db.rows(CHAIN_SQL, [measure, court, fy])
    ]


def _years(db: Database, measure: str, court: str) -> list[int]:
    return [r[0] for r in db.rows(YEARS_SQL, [measure, court])]


def _missing(db: Database, m: Measure, court: str, fy: int) -> Exception:
    years = _years(db, m.id, court)
    name = COURTS[court].citation or COURTS[court].name
    if not years:
        if court in TERRITORIAL and m.family in {"per_judgeship"}:
            why = (
                "Table X-1A excludes the territorial courts (they're outside the FJC "
                "case-weight studies)"
            )
        elif COURTS[court].level is not CourtLevel.NATIONAL and not (
            {"X-1A", "C-1", "C-5"} & set(m.tables)
        ):
            why = (
                f"{m.label} is published only nationally (Table {', '.join(m.tables)})"
            )
        else:
            why = "no table in the catalog prints it"
        return NotPublishedError(
            f"{m.label} for {name} isn't published: {why}.",
            ["compare_courts", "explain_term"],
        )
    return OutOfScopeError(
        f"{m.label} for {name} isn't published for FY{fy}. Available years: "
        f"{', '.join(str(y) for y in years)}.",
        [f"get_official_figure with fiscal_year in {years[0]}–{years[-1]}"],
    )


def revision_status(chain: list[_Row]) -> RevisionStatus:
    if len(chain) == 1:
        return "only_edition"
    return "revised" if len({r.shown for r in chain}) > 1 else "original"


def _later_revisions(chain: list[_Row]) -> list[FigureRef]:
    return [cur.ref() for prev, cur in pairwise(chain) if cur.shown != prev.shown]


def history_text(chain: list[_Row]) -> str:
    """'554 (JB-2020 to JFF-2022) → 322 (JFF-2023 to JFF-2025)'."""
    runs: list[tuple[float, str, str]] = []
    for r in chain:
        if runs and runs[-1][0] == r.shown:
            runs[-1] = (r.shown, runs[-1][1], r.edition)
        else:
            runs.append((r.shown, r.edition, r.edition))
    return " → ".join(
        f"{fmt(v)} ({a})" if a == b else f"{fmt(v)} ({a} to {b})" for v, a, b in runs
    )


def _select(chain: list[_Row], edition: str | None) -> _Row:
    if edition in (None, "latest"):
        return chain[-1]
    if edition == "first_published":
        return chain[0]
    for row in chain:
        if row.edition == edition:
            return row
    if edition not in EDITIONS:
        raise UnknownEditionError(f"Unknown edition {edition!r}.")
    printed = ", ".join(r.edition for r in chain)
    raise UnknownEditionError(
        f"{edition} doesn't print this figure. Editions that do: {printed}.",
        [f"call again with edition in [{printed}] or 'latest'"],
    )


def get_official_figure(
    db: Database,
    measure: str,
    court: str,
    fiscal_year: int,
    edition: str | None = None,
) -> Result[OfficialFigure]:
    """A published figure with its edition, definition and revision history."""
    m = get_measure(measure)
    _check_court(court)
    chain = _chain(db, measure, court, fiscal_year)
    if not chain:
        raise _missing(db, m, court, fiscal_year)
    row = _select(chain, edition)
    status = revision_status(chain)
    first, latest = chain[0], chain[-1]
    footnote_ids = row.footnote_ids
    footnotes = (
        [r[0] for r in db.rows(FOOTNOTES_SQL, [footnote_ids])] if footnote_ids else []
    )
    period = Period.for_end(fiscal_year, row.period_end)
    court_obj = COURTS[court]
    figure = OfficialFigure(
        measure=m.id,
        measure_label=m.label,
        unit=m.unit,
        court=court,
        court_name=court_obj.citation or court_obj.name,
        fiscal_year=fiscal_year,
        value=row.shown,
        edition=row.edition,
        table_code=row.table_code,
        period=period,
        revision_status=status,
        first_published=first.ref(),
        latest=latest.ref(),
        editions=[r.ref() for r in chain],
        footnotes=footnotes,
    )
    warnings: list[Caveat] = []
    nxt: list[str] = []
    if status == "revised":
        history = history_text(chain)
        warnings.append(
            Caveat(
                code="revised_figure",
                message=(
                    f"This figure was revised between editions ({history}). Report "
                    f"which edition you quote; don't average or mix them."
                ),
            )
        )
        if row is not latest and row.shown != latest.shown:
            warnings.append(
                Caveat(
                    code="revised_figure",
                    message=f"The current official figure is {fmt(latest.shown)} "
                    f"({latest.edition}).",
                )
            )
        nxt.append(
            f"explain_change or courts://revisions for why {m.label} FY{fiscal_year} "
            "changed between editions"
        )
    if period.period_type == "statistical_year":
        warnings.append(
            Caveat(
                code="period_mismatch",
                message=(
                    f"{fiscal_year} here is a statistical year: the 12 months ending "
                    f"June 30, {fiscal_year}, not a fiscal year ending September 30."
                ),
            )
        )
    prov = Provenance(
        source="official_table",
        table_code=row.table_code,
        series=series_title(row.edition),
        edition=row.edition,
        period=period,
        definition=m.definition,
        url=row.url,
        cell_ref=row.cell_ref,
        revision_status=status,
        first_published=first.ref(),
        later_revisions=_later_revisions(chain),
    )
    return ok(figure, [prov], warnings, nxt)


def _expand(courts: list[str] | None) -> list[str]:
    if not courts:
        return [c for c, v in COURTS.items() if v.level is CourtLevel.DISTRICT]
    out: list[str] = []
    for c in courts:
        _check_court(c)
        if c not in out:
            out.append(c)
    return out


def compare_courts(
    db: Database,
    measure: str,
    fiscal_year: int,
    courts: list[str] | None = None,
    edition: str | None = None,
    top_n: int | None = None,
    order: Literal["desc", "asc"] = "desc",
) -> Result[CourtComparison]:
    """Rank courts on one measure. Every value comes from one edition."""
    m = get_measure(measure)
    wanted = _expand(courts)
    candidates = db.rows(EDITION_ROWS_SQL, [measure, fiscal_year, wanted])
    if not candidates:
        if not _years(db, measure, wanted[0]) and len(wanted) == 1:
            raise _missing(db, m, wanted[0], fiscal_year)
        raise OutOfScopeError(
            f"No edition prints {m.label} for these courts in FY{fiscal_year}.",
            ["get_official_figure for the national figure"],
        )
    if edition in (None, "latest"):
        # The latest edition printing the most of the requested courts.
        best = max(candidates, key=lambda r: (r[2], r[1]))
        chosen = best[0]
    elif edition == "first_published":
        chosen = min(candidates, key=lambda r: r[1])[0]
    else:
        chosen = str(edition)
        if chosen not in {r[0] for r in candidates}:
            raise UnknownEditionError(
                f"{chosen} prints no {m.label} for these courts in FY{fiscal_year}. "
                f"Editions that do: {', '.join(r[0] for r in candidates)}."
            )
    rows = db.rows(COMPARE_SQL, [measure, fiscal_year, chosen, wanted])
    by_court = {r[0]: r for r in rows}
    ranked = sorted(
        (r for r in rows if r[0] != "US"),
        key=lambda r: r[1],
        reverse=order == "desc",
    )
    if top_n:
        ranked = ranked[:top_n]
    table_code = rows[0][4]
    url = rows[0][5]
    period_end = rows[0][6]
    out_rows = [
        CourtRow(
            rank=i,
            court=c,
            court_name=COURTS[c].name,
            citation=COURTS[c].citation,
            value=round_half_up(v, d or 0),
            cell_ref=cell,
        )
        for i, (c, v, d, cell, *_rest) in enumerate(ranked, 1)
    ]
    national_chain = _chain(db, measure, "US", fiscal_year)
    national = next((r for r in national_chain if r.edition == chosen), None)
    latest_national = national_chain[-1] if national_chain else None
    warnings: list[Caveat] = []
    national_latest = None
    if national and latest_national and latest_national.shown != national.shown:
        national_latest = latest_national.ref()
        warnings.append(
            Caveat(
                code="revised_figure",
                message=(
                    f"Court values are only published in {chosen}. The national "
                    f"figure in that edition is {fmt(national.shown)}; "
                    f"{latest_national.edition} later revised it to "
                    f"{fmt(latest_national.shown)}. Compare courts with the {chosen} "
                    "national figure, not the revised one."
                ),
            )
        )
    missing = [c for c in wanted if c not in by_court and c != "US"]
    if courts is None:
        missing = [c for c in missing if c not in TERRITORIAL]
    prov = Provenance(
        source="official_table",
        table_code=table_code,
        series=series_title(chosen),
        edition=chosen,
        period=Period.for_end(fiscal_year, period_end),
        definition=m.definition,
        url=url,
        note=f"All {len(rows)} values from {chosen} Table {table_code}.",
    )
    data = CourtComparison(
        measure=m.id,
        measure_label=m.label,
        unit=m.unit,
        fiscal_year=fiscal_year,
        edition=chosen,
        table_code=table_code,
        order=order,
        rows=out_rows,
        national=national.ref() if national else None,
        national_latest=national_latest,
        not_published=missing,
        total_courts=len([r for r in rows if r[0] != "US"]),
    )
    return ok(data, [prov], warnings)
