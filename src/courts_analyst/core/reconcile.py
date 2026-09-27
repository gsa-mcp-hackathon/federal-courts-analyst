"""reconcile: does the IDB reproduce a published count, and if not, why?

For civil cases filed, terminated and pending (Table C-1) by court and fiscal
year, the IDB rebuild is compared with the official figure and classified:

``matched``
    within the measure's tolerance of the latest edition's value.
``explained_variance``
    outside tolerance, but a quantified, known cause covers the gap:

    - *restated*: an earlier or later edition printed a value the IDB matches
      (the AO restates the prior year's closing pending count);
    - *repeat records*: filings: the IDB counts a case once, and the court-year
      has at least as many repeat records (reopened and re-terminated cases)
      as the gap; pending: records whose earlier termination falls after the
      date (undated reopenings, the ``reopened-without-date`` data break)
      cover the gap;
    - *snapshot drift*: the gap is within the snapshot allowance (records
      corrected since the table was published) for that measure.
``unexplained``
    none of the above.

Tolerances are per measure and set before looking at the variance report:
terminations must match to 0.05% (they reproduce C-1 exactly nationally),
filings 0.5%, pending 1%.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from courts_analyst.core.cohorts import (
    CohortSpec,
    CohortStore,
    expand_courts,
    idb_provenance,
)
from courts_analyst.core.courts import COURTS
from courts_analyst.core.db import Database
from courts_analyst.core.errors import OutOfScopeError
from courts_analyst.core.measures import PENDING_WHERE, get_measure
from courts_analyst.core.numbers import fmt, round_half_up
from courts_analyst.core.official import CHAIN_SQL, _Row
from courts_analyst.core.provenance import (
    BadgeStatus,
    FigureRef,
    Period,
    Provenance,
    ReconciliationBadge,
    series_title,
)
from courts_analyst.core.results import Caveat, Result, ok


@dataclass(frozen=True)
class Tolerance:
    pct: float
    abs: int
    snapshot_pct: float
    """Gaps up to this are 'snapshot drift' (records corrected since publication)."""


TOLERANCES: dict[str, Tolerance] = {
    "civil_cases_terminated": Tolerance(pct=0.05, abs=2, snapshot_pct=0.5),
    "civil_cases_filed": Tolerance(pct=0.5, abs=10, snapshot_pct=2.0),
    "civil_cases_pending": Tolerance(pct=1.0, abs=25, snapshot_pct=3.0),
}

Cause = Literal["restated", "repeat_records", "undated_reopenings", "snapshot_drift"]


class Explanation(BaseModel):
    cause: Cause
    detail: str
    quantity: float | None = Field(
        default=None, description="Size of the effect, in cases, where measured."
    )


class Reconciliation(BaseModel):
    """An IDB rebuild of a published count, compared with the table."""

    measure: str
    measure_label: str
    court: str
    court_name: str
    fiscal_year: int
    official: FigureRef
    official_editions: list[FigureRef]
    idb_value: int
    variance: float
    variance_pct: float | None
    tolerance_pct: float
    status: BadgeStatus
    explanations: list[Explanation] = Field(default_factory=list)
    badge: ReconciliationBadge
    rule: str = Field(description="How the IDB value was computed.")


RULE_TEXT = {
    "filed": "Cases with an AO filing date in the fiscal year, counted once per case "
    "(district, office, docket, filing date).",
    "terminated": "Every terminated record with an AO termination date in the fiscal "
    "year (a re-terminated case counts each time, as in Table C-1).",
    "pending": "Records filed by September 30, not terminated by then, and, for a "
    "repeat record, whose earlier termination was on or before that date.",
}


def _idb_value(db: Database, rule: str, districts: list[str], fy: int) -> int:
    if rule == "filed":
        sql = (
            "SELECT count(*) FROM idb.idb_civil WHERE filing_fy = ? "
            "AND list_contains(?, court)"
        )
        params: list[object] = [fy, districts]
    elif rule == "terminated":
        sql = (
            "SELECT count(*) FROM idb.idb_civil_terminations WHERE termination_fy = ? "
            "AND list_contains(?, court)"
        )
        params = [fy, districts]
    else:
        d = date(fy, 9, 30)
        sql = (
            "SELECT count(*) FROM idb.idb_civil_record WHERE "
            + PENDING_WHERE
            + " AND list_contains(?, court)"
        )
        params = [d, d, d, districts]
    row = db.one(sql, params)
    return int(row[0]) if row else 0


def _repeat_records(db: Database, districts: list[str], fy: int) -> int:
    row = db.one(
        "SELECT count(*) - count(DISTINCT case_key) FROM idb.idb_civil_record "
        "WHERE filing_fy = ? AND list_contains(?, court)",
        [fy, districts],
    )
    return int(row[0]) if row else 0


def _undated_reopenings(db: Database, districts: list[str], fy: int) -> int:
    """Repeat records filed by D whose previous termination is after D: open on
    D in the AO's count if the case was reopened by then, but the IDB can't
    tell when it was."""
    d = date(fy, 9, 30)
    row = db.one(
        "SELECT count(*) FROM idb.idb_civil_record WHERE filing_date_ao <= ? "
        "AND (termination_date_ao IS NULL OR termination_date_ao > ?) "
        "AND prev_termination_date_ao > ? AND list_contains(?, court)",
        [d, d, d, districts],
    )
    return int(row[0]) if row else 0


def classify(
    measure: str,
    official: float,
    idb: int,
    other_editions: list[float],
    repeat_records: int = 0,
    undated_reopenings: int = 0,
) -> tuple[BadgeStatus, list[Explanation]]:
    """Pure classification (unit-tested without a database)."""
    tol = TOLERANCES[measure]
    gap = idb - official
    allowed = max(tol.abs, abs(official) * tol.pct / 100)
    if abs(gap) <= allowed:
        return "matched", []
    out: list[Explanation] = []
    for other in other_editions:
        if abs(idb - other) <= max(tol.abs, abs(other) * tol.pct / 100):
            out.append(
                Explanation(
                    cause="restated",
                    detail=f"Another edition printed {fmt(other)}, which the IDB "
                    "matches within tolerance.",
                    quantity=other - official,
                )
            )
            return "explained_variance", out
    if measure == "civil_cases_filed" and gap < 0 and repeat_records >= abs(gap):
        out.append(
            Explanation(
                cause="repeat_records",
                detail=f"The IDB counts each case once; this court-year has "
                f"{repeat_records:,} repeat records (reopened or re-terminated), "
                f"more than the {abs(gap):,.0f}-case gap.",
                quantity=repeat_records,
            )
        )
        return "explained_variance", out
    if (
        measure == "civil_cases_pending"
        and gap < 0
        and undated_reopenings >= abs(gap) - allowed
    ):
        out.append(
            Explanation(
                cause="undated_reopenings",
                detail=f"{undated_reopenings:,} records were terminated before and "
                "again after this date; the IDB doesn't record when they were "
                "reopened (data break reopened-without-date), so the rebuild can't "
                "count them as pending.",
                quantity=undated_reopenings,
            )
        )
        return "explained_variance", out
    if abs(gap) <= abs(official) * tol.snapshot_pct / 100:
        out.append(
            Explanation(
                cause="snapshot_drift",
                detail=f"A {abs(gap) / official:.2%} gap, within the "
                f"{tol.snapshot_pct}% allowance for records corrected since the "
                "table was published (the IDB is a later snapshot).",
                quantity=abs(gap),
            )
        )
        return "explained_variance", out
    return "unexplained", []


def _chain(db: Database, measure: str, court: str, fy: int) -> list[_Row]:
    return [
        _Row(e, t, v, d if d is not None else 0, p, c, u, pe, list(f or []))
        for e, t, v, d, p, c, u, pe, f in db.rows(CHAIN_SQL, [measure, court, fy])
    ]


def reconcile_figure(
    db: Database, measure: str, court: str, fiscal_year: int
) -> Result[Reconciliation]:
    """Rebuild one C-1 count from the IDB and explain any variance."""
    db.require_idb()
    m = get_measure(measure)
    if m.idb is None or measure not in TOLERANCES:
        raise OutOfScopeError(
            f"reconcile rebuilds civil cases filed, terminated and pending; "
            f"{m.label} has no IDB counterpart.",
            ["get_official_figure"],
        )
    chain = _chain(db, measure, court, fiscal_year)
    if not chain:
        raise OutOfScopeError(
            f"{m.label} for {court} isn't published for FY{fiscal_year}.",
            ["get_official_figure"],
        )
    latest = chain[-1]
    districts = expand_courts([court])
    idb = _idb_value(db, m.idb, districts, fiscal_year)
    others = [r.shown for r in chain[:-1] if r.shown != latest.shown]
    repeat = _repeat_records(db, districts, fiscal_year) if m.idb == "filed" else 0
    reopen = (
        _undated_reopenings(db, districts, fiscal_year) if m.idb == "pending" else 0
    )
    status, why = classify(measure, latest.shown, idb, others, repeat, reopen)
    gap = idb - latest.shown
    pct = gap / latest.shown * 100 if latest.shown else None
    badge = ReconciliationBadge(
        status=status,
        official_value=latest.shown,
        idb_value=idb,
        variance=gap,
        variance_pct=pct,
        explanation=why[0].detail if why else None,
    )
    court_obj = COURTS[court]
    data = Reconciliation(
        measure=measure,
        measure_label=m.label,
        court=court,
        court_name=court_obj.citation or court_obj.name,
        fiscal_year=fiscal_year,
        official=latest.ref(),
        official_editions=[r.ref() for r in chain],
        idb_value=idb,
        variance=gap,
        variance_pct=pct,
        tolerance_pct=TOLERANCES[measure].pct,
        status=status,
        explanations=why,
        badge=badge,
        rule=RULE_TEXT[m.idb],
    )
    prov = [
        Provenance(
            source="official_table",
            table_code=latest.table_code,
            series=series_title(latest.edition),
            edition=latest.edition,
            period=Period.for_end(fiscal_year, latest.period_end),
            definition=m.definition,
            url=latest.url,
            cell_ref=latest.cell_ref,
            reconciliation=badge,
        ),
        idb_provenance(db, RULE_TEXT[m.idb]),
    ]
    warnings: list[Caveat] = []
    if status == "unexplained":
        warnings.append(
            Caveat(
                code="inexact_match",
                message=f"The IDB rebuild differs from the published figure by "
                f"{gap:+,.0f} ({pct:+.2f}%) and no known cause covers it.",
            )
        )
    return ok(data, prov, warnings)


def reconcile_cohort(
    db: Database, store: CohortStore, handle: str
) -> Result[Reconciliation]:
    """Reconcile a cohort when it corresponds to a published count: one fiscal
    year, courts that form a district, a circuit or the nation, and no filters
    beyond the basis."""
    spec = store.get(handle).spec
    norm = spec.normalized()
    extra = set(norm) - {"courts", "fy_from", "fy_to", "basis"}
    court = _single_court(spec)
    if extra or spec.fy_from != spec.fy_to or court is None:
        raise OutOfScopeError(
            "This cohort has no published counterpart: Table C-1 reports all civil "
            "cases for a court and fiscal year, without case-type or other filters. "
            "Reconcile a cohort with only courts, one fiscal year and a basis, or "
            "call reconcile with a measure, court and fiscal year.",
            ["reconcile(measure=..., court=..., fiscal_year=...)"],
        )
    measure = (
        "civil_cases_terminated" if spec.basis == "terminated" else "civil_cases_filed"
    )
    return reconcile_figure(db, measure, court, spec.fy_from)


def _single_court(spec: CohortSpec) -> str | None:
    wanted = sorted(expand_courts(spec.courts or ["US"]))
    for code in COURTS:
        if sorted(expand_courts([code])) == wanted:
            return code
    return None


# ── Variance report (every court × fiscal year × measure, in bulk) ──────────


class VarianceRow(BaseModel):
    measure: str
    court: str
    fiscal_year: int
    official: float
    edition: str
    idb: int
    variance: float
    variance_pct: float | None
    status: BadgeStatus
    cause: Cause | None = None


def _bulk_counts(db: Database, fys: list[int]) -> dict[tuple[str, str, int], int]:
    out: dict[tuple[str, str, int], int] = {}
    for measure, sql in (
        (
            "civil_cases_filed",
            "SELECT court, filing_fy, count(*) FROM idb.idb_civil "
            "WHERE list_contains(?, filing_fy) GROUP BY ALL",
        ),
        (
            "civil_cases_terminated",
            "SELECT court, termination_fy, count(*) FROM idb.idb_civil_terminations "
            "WHERE list_contains(?, termination_fy) GROUP BY ALL",
        ),
    ):
        for court, fy, n in db.rows(sql, [fys]):
            out[(measure, court, fy)] = n
    for fy in fys:
        d = date(fy, 9, 30)
        for court, n in db.rows(
            "SELECT court, count(*) FROM idb.idb_civil_record WHERE "
            + PENDING_WHERE
            + " GROUP BY ALL",
            [d, d, d],
        ):
            out[("civil_cases_pending", court, fy)] = n
    return out


def _bulk_aux(db: Database, fys: list[int]) -> tuple[dict[tuple[str, int], int], ...]:
    repeat: dict[tuple[str, int], int] = {
        (c, fy): n
        for c, fy, n in db.rows(
            "SELECT court, filing_fy, count(*) - count(DISTINCT case_key) "
            "FROM idb.idb_civil_record WHERE list_contains(?, filing_fy) GROUP BY ALL",
            [fys],
        )
    }
    reopen: dict[tuple[str, int], int] = {}
    for fy in fys:
        d = date(fy, 9, 30)
        for c, n in db.rows(
            "SELECT court, count(*) FROM idb.idb_civil_record "
            "WHERE filing_date_ao <= ? "
            "AND (termination_date_ao IS NULL OR termination_date_ao > ?) "
            "AND prev_termination_date_ao > ? GROUP BY ALL",
            [d, d, d],
        ):
            reopen[(c, fy)] = n
    return repeat, reopen


def variance_rows(db: Database, fys: list[int]) -> list[VarianceRow]:
    """Reconcile every district, circuit and the nation for ``fys``."""
    db.require_idb()
    counts = _bulk_counts(db, fys)
    repeat, reopen = _bulk_aux(db, fys)
    chains: dict[tuple[str, str, int], list[tuple[str, float]]] = {}
    for measure, court, fy, edition, value, decimals in db.rows(
        "SELECT o.measure_id, o.court, o.fiscal_year, o.edition, o.value, o.decimals "
        "FROM cat.observation o JOIN cat.edition e USING (edition) "
        "WHERE list_contains(?, o.measure_id) AND list_contains(?, o.fiscal_year) "
        "AND o.value IS NOT NULL ORDER BY e.pub_order",
        [list(TOLERANCES), fys],
    ):
        chains.setdefault((measure, court, fy), []).append(
            (edition, round_half_up(value, decimals or 0))
        )
    rows: list[VarianceRow] = []
    for (measure, court, fy), chain in sorted(chains.items()):
        if court not in COURTS:
            continue
        members = expand_courts([court])
        idb = sum(counts.get((measure, d, fy), 0) for d in members)
        rep = sum(repeat.get((d, fy), 0) for d in members)
        reo = sum(reopen.get((d, fy), 0) for d in members)
        edition, official = chain[-1]
        others = [v for _, v in chain[:-1] if v != official]
        status, why = classify(measure, official, idb, others, rep, reo)
        gap = idb - official
        rows.append(
            VarianceRow(
                measure=measure,
                court=court,
                fiscal_year=fy,
                official=official,
                edition=edition,
                idb=idb,
                variance=gap,
                variance_pct=gap / official * 100 if official else None,
                status=status,
                cause=why[0].cause if why else None,
            )
        )
    return rows
