"""Cohorts of IDB civil cases, addressed by deterministic handles.

``find_cases`` turns a :class:`CohortSpec` into a short handle (``coh_…``)
plus a summary; ``analyze_cohort`` computes a metric for a handle; ``refine``
narrows a cohort and keeps its lineage. The agent passes handles between
turns instead of rows, so no case list ever goes through the model's context,
and no row-level party data exists in the IDB database at all.

A handle is a hash of the normalised spec, so the same question gives the
same handle in every session, test and server replica.

Grain (Phase 2): cohorts on filings use ``idb_civil`` (one row per case, its
latest record); cohorts on terminations use ``idb_civil_terminations`` (every
terminated record), which reproduces Table C-1 exactly.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from courts_analyst.core.courts import COURTS, CourtLevel
from courts_analyst.core.db import Database
from courts_analyst.core.enums import (
    CourtCode,
    DispositionGroup,
    JurisdictionGroup,
    NosCategory,
    NosCode,
    NosGroup,
    OriginGroup,
    ProSeGroup,
    nos_entry,
)
from courts_analyst.core.errors import InvalidCohortError, UnknownHandleError
from courts_analyst.core.guardrails import guarded
from courts_analyst.core.guardrails.small_cells import protect
from courts_analyst.core.provenance import Provenance
from courts_analyst.core.results import Caveat, Result, ok
from courts_analyst.core.stats import (
    SMALL_CELL_SUPPRESS,
    SMALL_CELL_WARN,
    cell_status,
    median_ci_ranks,
    wilson,
)

FY_MIN, FY_MAX = 2015, 2025

Basis = Literal["filed", "terminated"]
Metric = Literal[
    "count",
    "trend",
    "median_days_to_disposition",
    "disposition_rates",
    "judgment_for_rates",
    "share_by_nos_group",
    "pro_se_share",
    "still_pending_share",
]
GroupBy = Literal["court", "fiscal_year", "nos_group", "origin"]

MAX_GROUPS = 25
DAYS_PER_MONTH = 30.4375


class CohortSpec(BaseModel):
    """Which civil cases are in the cohort. Every filter is optional; lists
    mean "any of". Courts may be districts or circuits (a circuit means all its
    districts); omit ``courts`` or pass ``US`` for every district."""

    model_config = ConfigDict(extra="forbid")

    courts: list[CourtCode] | None = Field(
        default=None, description="District or circuit codes; omit for all districts."
    )
    fy_from: int = Field(ge=FY_MIN, le=FY_MAX, description="First fiscal year.")
    fy_to: int = Field(ge=FY_MIN, le=FY_MAX, description="Last fiscal year.")
    basis: Basis = Field(
        default="filed",
        description="'filed': cases filed in those fiscal years. 'terminated': "
        "terminations in those fiscal years (every termination counts, as in "
        "Table C-1).",
    )
    nos_codes: list[NosCode] | None = Field(
        default=None,
        description="Nature-of-suit codes, for example ['442'] or ['830'].",
    )
    nos_groups: list[NosGroup] | None = Field(
        default=None, description="Table C-2 groups, for example ['Civil Rights']."
    )
    nos_categories: list[NosCategory] | None = None
    origins: list[OriginGroup] | None = Field(
        default=None,
        description="Origins to include, for example ['mdl_direct'] for directly "
        "filed MDL cases.",
    )
    exclude_mdl: bool = Field(
        default=False,
        description="Drop MDL cases (directly filed and transferred in by the JPML).",
    )
    jurisdictions: list[JurisdictionGroup] | None = None
    dispositions: list[DispositionGroup] | None = Field(
        default=None, description="Only terminated cases with these dispositions."
    )
    pro_se: list[ProSeGroup] | None = Field(
        default=None, description="Who was pro se: plaintiff, defendant, both, none."
    )
    class_action: bool | None = Field(
        default=None, description="True: class action alleged at filing."
    )
    mdl_docket: str | None = Field(
        default=None,
        pattern=r"^\d{1,5}$",
        description="An MDL docket number, for example '2885'.",
    )

    @model_validator(mode="after")
    def _years(self) -> CohortSpec:
        if self.fy_from > self.fy_to:
            raise ValueError("fy_from must be <= fy_to")
        if (
            self.exclude_mdl
            and self.origins
            and ({"mdl_direct", "mdl_transfer"} & set(self.origins))
        ):
            raise ValueError("exclude_mdl contradicts origins that are MDL")
        return self

    def normalized(self) -> dict[str, Any]:
        """Canonical form: sorted de-duplicated lists, circuits and 'US'
        expanded to districts, defaults dropped. Equal specs → equal dicts."""
        data = self.model_dump(exclude_defaults=True)
        data["fy_from"], data["fy_to"] = self.fy_from, self.fy_to
        if self.courts:
            districts = expand_courts(list(self.courts))
            all_d = [c for c, v in COURTS.items() if v.level is CourtLevel.DISTRICT]
            if sorted(districts) == sorted(all_d):
                data.pop("courts")
            else:
                data["courts"] = sorted(districts)
        for key, val in list(data.items()):
            if isinstance(val, list):
                data[key] = sorted(set(val))
        return data

    def handle(self) -> str:
        blob = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":"))
        return "coh_" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def expand_courts(courts: Sequence[str]) -> list[str]:
    out: list[str] = []
    for code in courts:
        court = COURTS[code]
        if court.level is CourtLevel.NATIONAL:
            members = [c for c, v in COURTS.items() if v.level is CourtLevel.DISTRICT]
        elif court.level is CourtLevel.CIRCUIT:
            members = [c for c, v in COURTS.items() if v.circuit == code]
        else:
            members = [code]
        out.extend(m for m in members if m not in out)
    return out


# ── SQL assembly: constant fragments + ? parameters only ────────────────────


def _source(spec: CohortSpec) -> tuple[str, str]:
    """(relation, fiscal-year column) for the spec's basis."""
    if spec.basis == "terminated":
        return "idb.idb_civil_terminations", "termination_fy"
    return "idb.idb_civil", "filing_fy"


def where_clause(spec: CohortSpec) -> tuple[str, list[Any]]:
    _, fy_col = _source(spec)
    parts = [fy_col + " BETWEEN ? AND ?"]
    params: list[Any] = [spec.fy_from, spec.fy_to]
    norm = spec.normalized()

    def any_of(column: str, values: list[Any] | None) -> None:
        if values:
            parts.append("list_contains(?, " + column + ")")
            params.append(list(values))

    any_of("court", norm.get("courts"))
    any_of("nos_code", spec.nos_codes)
    any_of("nos_group", spec.nos_groups)
    any_of("nos_category", spec.nos_categories)
    any_of("origin_group", spec.origins)
    any_of("jurisdiction_group", spec.jurisdictions)
    any_of("disposition_group", spec.dispositions)
    any_of("pro_se_group", spec.pro_se)
    if spec.exclude_mdl:
        parts.append("NOT (is_mdl_direct_filed OR is_mdl_transferred)")
    if spec.class_action is not None:
        parts.append("coalesce(is_class_action, false) = ?")
        params.append(spec.class_action)
    if spec.mdl_docket:
        parts.append("mdl_docket = ?")
        params.append(spec.mdl_docket.lstrip("0") or "0")
    return " AND ".join(parts), params


def _from_where(spec: CohortSpec) -> tuple[str, list[Any]]:
    rel, _ = _source(spec)
    where, params = where_clause(spec)
    return " FROM " + rel + " WHERE " + where, params


def fingerprint(spec: CohortSpec) -> str:
    sql, params = _from_where(spec)
    blob = sql + json.dumps(params, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ── Store ────────────────────────────────────────────────────────────────────


class CohortRecord(BaseModel):
    handle: str
    spec: CohortSpec
    n: int
    parent: str | None = None
    fingerprint: str
    created_at: str


class CohortStore:
    """Handles → specs. An in-process LRU, optionally backed by a small DuckDB
    file so handles survive a restart in HTTP mode. Because handles are
    deterministic, a lost handle is recreated by calling ``find_cases`` again."""

    def __init__(self, path: Path | None = None, capacity: int = 2048) -> None:
        self._mem: OrderedDict[str, CohortRecord] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()
        self._path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(path)) as con:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS cohort (handle VARCHAR PRIMARY KEY, "
                    "record VARCHAR)"
                )

    def put(self, record: CohortRecord) -> None:
        with self._lock:
            self._mem[record.handle] = record
            self._mem.move_to_end(record.handle)
            while len(self._mem) > self._capacity:
                self._mem.popitem(last=False)
            if self._path is not None:
                with duckdb.connect(str(self._path)) as con:
                    con.execute(
                        "INSERT OR REPLACE INTO cohort VALUES (?, ?)",
                        [record.handle, record.model_dump_json()],
                    )

    def get(self, handle: str) -> CohortRecord:
        with self._lock:
            if handle in self._mem:
                self._mem.move_to_end(handle)
                return self._mem[handle]
            if self._path is not None:
                with duckdb.connect(str(self._path), read_only=True) as con:
                    row = con.execute(
                        "SELECT record FROM cohort WHERE handle = ?", [handle]
                    ).fetchone()
                if row:
                    rec = CohortRecord.model_validate_json(row[0])
                    self._mem[handle] = rec
                    return rec
        raise UnknownHandleError(
            f"Unknown cohort handle {handle!r}. Handles come from find_cases; "
            "call it again with the same filters to get the handle back.",
            ["find_cases"],
        )


# ── Results ──────────────────────────────────────────────────────────────────


class Count(BaseModel):
    key: str
    n: int | None = Field(description="Cases; None when suppressed (fewer than 10).")
    share: float | None = None
    suppressed: bool = Field(
        default=False,
        description="Withheld: fewer than 10 cases, or withheld so a small cell "
        "can't be worked out from the total.",
    )


class CohortSummary(BaseModel):
    """A cohort's handle and a small preview: never rows, never names."""

    handle: str
    parent: str | None = None
    spec: dict[str, Any] = Field(description="The normalised filters.")
    basis: Basis
    n: int | None = Field(
        description="Cases (filed basis) or terminations (terminated basis); None "
        "when fewer than 10 (suppressed)."
    )
    by_fiscal_year: list[Count]
    top_courts: list[Count]
    top_nos_groups: list[Count]
    mdl_direct_share: float | None
    terminated_share: float | None = Field(
        default=None, description="Share of the cohort already terminated."
    )


class GroupValue(BaseModel):
    group: str | None = Field(default=None, description="Group key, or None for all.")
    n: int | None = Field(
        description="Cases the value is computed over; None when suppressed."
    )
    value: float | None = Field(description="None when withheld (fewer than 10 cases).")
    ci_low: float | None = None
    ci_high: float | None = None
    breakdown: list[Count] | None = None
    status: Literal["ok", "small", "suppressed"] = "ok"


class CohortAnalysis(BaseModel):
    handle: str
    metric: Metric
    unit: str
    group_by: GroupBy | None
    results: list[GroupValue]
    groups_omitted: int = 0
    method: str


def idb_provenance(
    db: Database, definition: str, note: str | None = None
) -> Provenance:
    row = db.one("SELECT url, coverage, last_modified FROM idb.idb_release LIMIT 1")
    return Provenance(
        source="idb_derived",
        series="FJC Integrated Database, civil",
        definition=definition,
        url=row[0] if row else None,
        dataset_release=(f"{row[2]} ({row[1]})" if row else None),
        note=note,
    )


def _counts(
    db: Database, spec: CohortSpec, column: str, total: int, limit: int | None = None
) -> list[Count]:
    """The cohort split by ``column``, largest first, with small cells (and
    their complements) suppressed across the *whole* split before the top
    ``limit`` are kept."""
    frm, params = _from_where(spec)
    sql = (
        "SELECT CAST("
        + column
        + " AS VARCHAR) AS k, count(*) AS n"
        + frm
        + " GROUP BY 1 ORDER BY n DESC, k"
    )
    rows = db.rows(sql, params)
    return protect_counts([(str(k), int(n)) for k, n in rows], total)[:limit]


def protect_counts(rows: list[tuple[str, int]], total: int | None) -> list[Count]:
    """Counts with the small-cell and complementary rules applied. ``total``
    is the published sum of the rows (None when it isn't shown)."""
    shown = total is not None and sum(n for _, n in rows) == total
    guard = protect([n for _, n in rows], total_shown=shown)
    return [
        Count(key=k, n=None, share=None, suppressed=True)
        if i in guard.withheld
        else Count(key=k, n=n, share=n / total if total else None)
        for i, (k, n) in enumerate(rows)
    ]


def _cell_caveats(n: int) -> list[Caveat]:
    status = cell_status(n)
    if status == "suppressed" and n > 0:
        return [
            Caveat(
                code="suppressed",
                severity="block",
                message=f"Fewer than {SMALL_CELL_SUPPRESS} cases: too few to report. "
                "The count and every statistic are withheld; broaden the filters.",
            )
        ]
    if status == "suppressed":
        return [
            Caveat(
                code="suppressed",
                severity="block",
                message="No cases to compute this over; broaden the filters.",
            )
        ]
    if status == "small":
        return [
            Caveat(
                code="small_cell",
                message=f"Only {n} cases match (fewer than {SMALL_CELL_WARN}); "
                "treat rates and medians as indicative.",
            )
        ]
    return []


def _data_break_caveats(db: Database, spec: CohortSpec) -> list[Caveat]:
    start = f"{spec.fy_from - 1}-10-01"
    end = f"{spec.fy_to}-09-30"
    rows = db.rows(
        "SELECT id, field, codes, summary FROM idb.data_breaks "
        "WHERE date >= CAST(? AS DATE) AND date <= CAST(? AS DATE) "
        "AND id <> 'release-snapshot'",
        [start, end],
    )
    groups = set(spec.nos_groups or [])
    codes_wanted = set(spec.nos_codes or [])
    out = []
    for bid, fld, codes, title in rows:
        if fld == "nos":
            hit = codes_wanted & set(codes or []) or any(
                (entry := nos_entry(c)) and entry.get("group") in groups
                for c in codes or []
            )
            if not hit:
                continue
        if fld == "origin" and not (
            spec.exclude_mdl or "mdl_direct" in (spec.origins or [])
        ):
            continue
        out.append(
            Caveat(code="data_break", message=f"{title} ({bid})", severity="info")
        )
    return out


def _suppressed_counts_caveat() -> Caveat:
    return Caveat(
        code="suppressed",
        severity="info",
        message=f"Groups with fewer than {SMALL_CELL_SUPPRESS} cases are shown as "
        "suppressed (n = null), and so is the next smallest where needed, so no "
        "small group can be worked out from the total.",
    )


@guarded
def find_cases(
    db: Database, store: CohortStore, spec: CohortSpec, parent: str | None = None
) -> Result[CohortSummary]:
    """Build (or look up) a cohort; return its handle and a preview."""
    db.require_idb()
    frm, params = _from_where(spec)
    row = db.one(
        "SELECT count(*), avg(CAST(is_mdl_direct_filed AS INTEGER)), "
        "avg(CAST(termination_date IS NOT NULL AS INTEGER))" + frm,
        params,
    )
    assert row is not None
    n = int(row[0])
    handle = spec.handle()
    store.put(
        CohortRecord(
            handle=handle,
            spec=spec,
            n=n,
            parent=parent,
            fingerprint=fingerprint(spec),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    )
    _, fy_col = _source(spec)
    small = 0 < n < SMALL_CELL_SUPPRESS
    shown = n > 0 and not small
    summary = CohortSummary(
        handle=handle,
        parent=parent,
        spec=spec.normalized(),
        basis=spec.basis,
        n=None if small else n,
        by_fiscal_year=sorted(_counts(db, spec, fy_col, n), key=lambda c: c.key)
        if shown
        else [],
        top_courts=_counts(db, spec, "court", n, 5) if shown else [],
        top_nos_groups=_counts(db, spec, "nos_group", n, 5) if shown else [],
        mdl_direct_share=float(row[1]) if row[1] is not None and shown else None,
        terminated_share=float(row[2]) if row[2] is not None and shown else None,
    )
    # An empty cohort isn't a suppressed one: out_of_scope below says so.
    warnings = (_cell_caveats(n) if n else []) + _data_break_caveats(db, spec)
    if any(
        c.suppressed
        for c in (*summary.by_fiscal_year, *summary.top_courts, *summary.top_nos_groups)
    ):
        warnings.append(_suppressed_counts_caveat())
    if n == 0:
        warnings.append(
            Caveat(code="out_of_scope", message="No cases match these filters.")
        )
    what = "cases filed" if spec.basis == "filed" else "terminations"
    prov = idb_provenance(
        db,
        f"Civil {what} in FY{spec.fy_from}–FY{spec.fy_to} matching the filters "
        "(AO fiscal-year dates; one row per case for filings, every terminated "
        "record for terminations).",
    )
    nxt = [f"analyze_cohort(handle='{handle}', metric=...)"]
    if shown:
        nxt.append(f"sample_dockets(handle='{handle}', n=3)")
    return ok(summary, [prov], warnings, nxt)


@guarded
def refine(
    db: Database, store: CohortStore, handle: str, changes: dict[str, Any]
) -> Result[CohortSummary]:
    """A narrower cohort: the parent's filters with ``changes`` applied."""
    parent = store.get(handle)
    merged = {**parent.spec.model_dump(exclude_defaults=True), **changes}
    merged.setdefault("fy_from", parent.spec.fy_from)
    merged.setdefault("fy_to", parent.spec.fy_to)
    try:
        spec = CohortSpec.model_validate(merged)
    except ValueError as exc:
        raise InvalidCohortError(str(exc)) from exc
    return find_cases(db, store, spec, parent=handle)


# ── Metrics ──────────────────────────────────────────────────────────────────

_GROUP_COLUMNS: dict[str, str] = {
    "court": "court",
    "fiscal_year": "__fy__",
    "nos_group": "nos_group",
    "origin": "origin_group",
}


def _group_col(spec: CohortSpec, group_by: GroupBy | None) -> str | None:
    if group_by is None:
        return None
    col = _GROUP_COLUMNS[group_by]
    return _source(spec)[1] if col == "__fy__" else col


def _groups(
    db: Database, spec: CohortSpec, col: str | None
) -> tuple[list[tuple[str | None, int]], int]:
    frm, params = _from_where(spec)
    if col is None:
        row = db.one("SELECT count(*)" + frm, params)
        return [(None, int(row[0]) if row else 0)], 0
    rows = db.rows(
        "SELECT CAST("
        + col
        + " AS VARCHAR), count(*) AS n"
        + frm
        + " GROUP BY 1 ORDER BY n DESC, 1",
        params,
    )
    if col.endswith("_fy"):
        rows = sorted(rows, key=lambda r: str(r[0]))
    omitted = max(0, len(rows) - MAX_GROUPS)
    return [(r[0], int(r[1])) for r in rows], omitted


def _with_group(
    spec: CohortSpec, col: str | None, key: str | None
) -> tuple[str, list[Any]]:
    frm, params = _from_where(spec)
    if col is None:
        return frm, params
    return frm + " AND CAST(" + col + " AS VARCHAR) IS NOT DISTINCT FROM ?", [
        *params,
        key,
    ]


def _median(db: Database, frm: str, params: list[Any]) -> GroupValue:
    base = frm + " AND days_to_disposition IS NOT NULL"
    row = db.one("SELECT count(*), median(days_to_disposition)" + base, params)
    n = int(row[0]) if row else 0
    status = cell_status(n)
    if status == "suppressed" or row is None or row[1] is None:
        return GroupValue(n=n, value=None, status="suppressed")
    ranks = median_ci_ranks(n)
    lo = hi = None
    if ranks:
        j, k = ranks
        q = db.one(
            "SELECT quantile_disc(days_to_disposition, [?, ?])" + base,
            [(j - 0.5) / n, (k - 0.5) / n, *params],
        )
        if q and q[0]:
            lo, hi = float(q[0][0]), float(q[0][1])
    return GroupValue(n=n, value=float(row[1]), ci_low=lo, ci_high=hi, status=status)


def _rates(
    db: Database, frm: str, params: list[Any], column: str, only_non_null: bool = True
) -> GroupValue:
    cond = " AND " + column + " IS NOT NULL" if only_non_null else ""
    rows = db.rows(
        "SELECT CAST("
        + column
        + " AS VARCHAR), count(*)"
        + frm
        + cond
        + " GROUP BY 1 ORDER BY 2 DESC, 1",
        params,
    )
    n = sum(r[1] for r in rows)
    status = cell_status(n)
    if status == "suppressed" or n == 0:
        return GroupValue(n=n, value=None, status="suppressed")
    top_k = rows[0][1]
    ci = wilson(top_k, n)
    return GroupValue(
        n=n,
        value=top_k / n,
        ci_low=ci.low,
        ci_high=ci.high,
        breakdown=protect_counts([(str(key), int(k)) for key, k in rows], n),
        status=status,
    )


def _share(
    db: Database, frm: str, params: list[Any], condition: str, n_filter: str = ""
) -> GroupValue:
    row = db.one(
        "SELECT count(*), sum(CASE WHEN "
        + condition
        + " THEN 1 ELSE 0 END)"
        + frm
        + n_filter,
        params,
    )
    n = int(row[0]) if row else 0
    k = int(row[1] or 0) if row else 0
    status = cell_status(n)
    if status == "suppressed" or n == 0:
        return GroupValue(n=n, value=None, status="suppressed")
    ci = wilson(k, n)
    return GroupValue(n=n, value=k / n, ci_low=ci.low, ci_high=ci.high, status=status)


_METHOD = {
    "count": ("cases", "Count of matching cases (or terminations)."),
    "trend": ("cases", "Count by fiscal year."),
    "median_days_to_disposition": (
        "days",
        "Median days from filing (FILEDATE) to termination (TERMDATE) over "
        "terminated cases; 95% distribution-free CI from order statistics.",
    ),
    "disposition_rates": (
        "share",
        "Share of terminated cases by disposition group (value = the most common); "
        "95% Wilson CI.",
    ),
    "judgment_for_rates": (
        "share",
        "Among cases with a recorded judgment, share by the party it favoured "
        "(value = the most common); 95% Wilson CI.",
    ),
    "share_by_nos_group": (
        "share",
        "Share of cases by Table C-2 nature-of-suit group.",
    ),
    "pro_se_share": (
        "share",
        "Share of cases with at least one pro se party at filing; 95% Wilson CI.",
    ),
    "still_pending_share": (
        "share",
        "Share of cases with no termination as of the IDB release; 95% Wilson CI.",
    ),
}


def _protect_groups(results: list[GroupValue], total: int) -> list[GroupValue]:
    """Withhold small groups (their n and value) and, when the groups' n add up
    to the cohort total the summary shows, enough others that none can be
    worked out from it."""
    counts = [r.n or 0 for r in results]
    guard = protect(counts, total_shown=sum(counts) == total)
    out = []
    for i, r in enumerate(results):
        if i in guard.withheld or r.status == "suppressed":
            out.append(
                r.model_copy(
                    update={
                        "n": None,
                        "value": None,
                        "ci_low": None,
                        "ci_high": None,
                        "breakdown": None,
                        "status": "suppressed",
                    }
                )
            )
        else:
            out.append(r)
    return out


@guarded
def analyze_cohort(
    db: Database,
    store: CohortStore,
    handle: str,
    metric: Metric,
    group_by: GroupBy | None = None,
) -> Result[CohortAnalysis]:
    """Compute a metric for a cohort, with n, a CI and small-cell rules."""
    db.require_idb()
    rec = store.get(handle)
    spec = rec.spec
    if metric == "trend":
        group_by = "fiscal_year"
    col = _group_col(spec, group_by)
    groups, omitted = _groups(db, spec, col)
    results: list[GroupValue] = []
    # Metrics run on the shown groups only; small-cell protection below sees
    # every group's count, so truncation can't expose a withheld one.
    all_counts = [gn for _, gn in groups]
    for key, gn in groups[:MAX_GROUPS]:
        frm, params = _with_group(spec, col, key)
        if metric in ("count", "trend"):
            gv = GroupValue(n=gn, value=float(gn), status=cell_status(gn))
        elif metric == "median_days_to_disposition":
            gv = _median(db, frm, params)
        elif metric == "disposition_rates":
            gv = _rates(db, frm, params, "disposition_group")
        elif metric == "judgment_for_rates":
            gv = _rates(db, frm, params, "judgment_for")
        elif metric == "share_by_nos_group":
            gv = _rates(db, frm, params, "nos_group")
        elif metric == "pro_se_share":
            gv = _share(
                db, frm, params, "pro_se_group IN ('plaintiff', 'defendant', 'both')"
            )
        else:
            gv = _share(db, frm, params, "termination_date IS NULL")
        results.append(gv.model_copy(update={"group": key}))
    unit, method = _METHOD[metric]
    warnings: list[Caveat] = []
    small = [r for r in results if r.status != "ok"]
    if small and metric not in ("count", "trend"):
        worst = min(r.n or 0 for r in small)
        warnings.extend(_cell_caveats(worst))
    elif metric in ("count", "trend") and rec.n < SMALL_CELL_WARN:
        warnings.extend(_cell_caveats(rec.n))
    if rec.n < SMALL_CELL_SUPPRESS:
        results = [
            r.model_copy(
                update={
                    "n": None,
                    "value": None,
                    "ci_low": None,
                    "ci_high": None,
                    "breakdown": None,
                    "status": "suppressed",
                }
            )
            for r in results
        ]
    else:
        # Every group's count feeds the protection, shown or not.
        padded = results + [
            GroupValue(n=gn, value=None, status="ok") for gn in all_counts[MAX_GROUPS:]
        ]
        if metric in ("count", "trend") or sum(r.n or 0 for r in padded) == rec.n:
            results = _protect_groups(padded, rec.n)[: len(results)]
        else:
            results = _protect_groups(padded, -1)[: len(results)]
        if any(r.status == "suppressed" and r.group is not None for r in results):
            warnings.append(_suppressed_counts_caveat())
    if omitted:
        warnings.append(
            Caveat(
                code="truncated",
                severity="info",
                message=f"Showing the {MAX_GROUPS} largest groups; {omitted} smaller "
                "groups omitted.",
            )
        )
    if metric == "still_pending_share" or (
        spec.basis == "filed"
        and spec.fy_to >= FY_MAX - 1
        and metric in ("median_days_to_disposition", "disposition_rates")
    ):
        warnings.append(
            Caveat(
                code="partial_year",
                message=(
                    "Recent cohorts are still open: medians and outcome rates cover "
                    "only cases already terminated, which skews toward quick "
                    "dispositions."
                ),
            )
        )
    warnings += _data_break_caveats(db, spec)
    data = CohortAnalysis(
        handle=handle,
        metric=metric,
        unit=unit,
        group_by=group_by,
        results=results,
        groups_omitted=omitted,
        method=method,
    )
    prov = idb_provenance(
        db, method, note=f"Cohort {handle}: {json.dumps(spec.normalized())}"
    )
    return ok(data, [prov], warnings)
