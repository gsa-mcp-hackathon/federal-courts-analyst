"""explain_change: why did a measure change between two fiscal years?

Two modes, chosen by the measure:

**Counts** (civil cases filed, terminated, pending). The total change comes
from the official Table C-1 (latest edition of each year). The IDB rebuilds
the same counts and splits the change by district and by nature-of-suit
group; each breakdown sums *exactly* to the IDB change (the rest goes to an
"all other" row), and any gap between the IDB and official change is shown,
never hidden.

**Per judgeship** (filings per authorized judgeship, weighted or not). A
per-judgeship value is F/J. Its change splits exactly into a *filings effect*
and a *judgeship effect* (a symmetric shift-share):

    Δ(F/J) = (F₂ − F₁)·(1/J₁ + 1/J₂)/2  +  (F₁ + F₂)/2·(1/J₂ − 1/J₁)

The filings effect is then split by district from Table X-1A (district value
× district judgeships = district filings). Only the first-published Judicial
Business series has district rows, so the decomposition uses it and says so;
later JFF revisions of the national figure are reported as a driver.

Both years' official values come from one consistent vintage (the
never-mix-vintages rule, ``core/guardrails/vintage``), and IDB breakdown rows
with fewer than 10 cases in both years fold into "All other" (with enough
others that none can be recovered), so the breakdowns still add up exactly.

**Drivers** are then detected and labelled by what backs them:
``official`` (read from a table), ``idb_derived`` (counted from IDB records),
``inferred`` (our reasoning, not an official statement) or ``context``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from courts_analyst.core.chain import Row, load_chain
from courts_analyst.core.cohorts import expand_courts, idb_provenance
from courts_analyst.core.courts import COURTS, CourtLevel
from courts_analyst.core.db import Database
from courts_analyst.core.errors import InvalidCohortError, OutOfScopeError
from courts_analyst.core.guardrails import guarded
from courts_analyst.core.guardrails.small_cells import protect_pairs
from courts_analyst.core.guardrails.vintage import choose_vintage
from courts_analyst.core.measures import PENDING_WHERE, Measure, get_measure
from courts_analyst.core.numbers import fmt, round_half_up
from courts_analyst.core.provenance import FigureRef, Period, Provenance, series_title
from courts_analyst.core.results import Caveat, Result, ok
from courts_analyst.core.revisions import revision_notes

KEY_SHARE = 0.8
"""Contributors are marked key until they explain this share of the change."""
MAX_ROWS = 10
Basis = Literal["official", "idb_derived", "inferred", "context"]

PANDEMIC_START = date(2020, 3, 13)
PANDEMIC_FYS = frozenset({2020, 2021})


class Contribution(BaseModel):
    key: str
    label: str
    value_from: float
    value_to: float
    change: float
    share_of_change: float | None = Field(
        description="change / total change (can exceed 1 when others offset it)."
    )
    key_contributor: bool = False


class Driver(BaseModel):
    code: Literal[
        "mdl_direct_filed",
        "mdl_cases",
        "pandemic_window",
        "methodology_revision",
        "data_break",
        "judgeship_change",
    ]
    title: str
    basis: Basis
    evidence: str
    magnitude: float | None = None
    share_of_change: float | None = None


class ChangeExplanation(BaseModel):
    """What changed, by how much, where, and what drove it."""

    measure: str
    measure_label: str
    unit: str
    court: str
    court_name: str
    period_from: int
    period_to: int
    mode: Literal["count", "per_judgeship"]
    headline: str
    official_from: FigureRef
    official_to: FigureRef
    official_change: float
    official_change_pct: float | None
    idb_from: int | None = None
    idb_to: int | None = None
    idb_change: int | None = Field(
        default=None, description="The same change rebuilt from IDB records."
    )
    idb_change_excluding_mdl_direct: int | None = Field(
        default=None,
        description="The IDB change with directly filed MDL cases taken out "
        "(filings only).",
    )
    filings_effect: float | None = Field(
        default=None, description="Part of the per-judgeship change due to filings."
    )
    judgeship_effect: float | None = Field(
        default=None, description="Part due to the change in authorized judgeships."
    )
    decomposition_series: str = Field(
        description="Which data the breakdowns come from."
    )
    by_district: list[Contribution] = Field(default_factory=list)
    by_case_type: list[Contribution] = Field(default_factory=list)
    by_district_and_case_type: list[Contribution] = Field(default_factory=list)
    drivers: list[Driver] = Field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────


def _need_chain(db: Database, m: Measure, court: str, fy: int) -> list[Row]:
    chain = load_chain(db, m.id, court, fy)
    if not chain:
        raise OutOfScopeError(
            f"{m.label} for {court} isn't published for FY{fy}.",
            ["get_official_figure to see which years are available"],
        )
    return chain


def _name(code: str) -> str:
    c = COURTS.get(code)
    return (c.citation or c.name) if c else code


def contributions(
    before: dict[str, float],
    after: dict[str, float],
    labels: dict[str, str] | None = None,
    limit: int = MAX_ROWS,
    other_label: str = "All other",
    small_cells: bool = False,
) -> list[Contribution]:
    """Per-key changes, largest first, that sum exactly to the total change.

    Keys beyond ``limit`` fold into one "All other" row; with ``small_cells``
    (case counts from the IDB) so do rows under 10 cases in both years, plus
    enough others that none of them can be recovered from the "All other"
    row. The first rows are marked ``key_contributor`` until their cumulative
    change reaches 80% of the total (in its direction).
    """
    keys = set(before) | set(after)
    total = sum(after.values()) - sum(before.values())
    rows = [(k, before.get(k, 0.0), after.get(k, 0.0)) for k in keys]
    rows.sort(key=lambda r: (-abs(r[2] - r[1]), r[0]))
    hidden = set(range(limit, len(rows)))
    if small_cells:
        hidden = protect_pairs([(a, b) for _, a, b in rows], hidden)
    head = [r for i, r in enumerate(rows) if i not in hidden]
    tail = [r for i, r in enumerate(rows) if i in hidden]
    out: list[Contribution] = []
    for k, a, b in head:
        out.append(
            Contribution(
                key=k,
                label=(labels or {}).get(k, k),
                value_from=a,
                value_to=b,
                change=b - a,
                share_of_change=(b - a) / total if total else None,
            )
        )
    if tail:
        a = sum(r[1] for r in tail)
        b = sum(r[2] for r in tail)
        out.append(
            Contribution(
                key="__other__",
                label=f"{other_label} ({len(tail)})",
                value_from=a,
                value_to=b,
                change=b - a,
                share_of_change=(b - a) / total if total else None,
            )
        )
    _mark_key(out, total)
    return out


def _mark_key(rows: list[Contribution], total: float) -> None:
    if not total:
        return
    direction = 1 if total > 0 else -1
    running = 0.0
    for r in sorted(
        (r for r in rows if r.key != "__other__"), key=lambda r: -direction * r.change
    ):
        if direction * running >= KEY_SHARE * abs(total) or direction * r.change <= 0:
            break
        r.key_contributor = True
        running += r.change


def shift_share(f1: float, j1: float, f2: float, j2: float) -> tuple[float, float]:
    """(filings effect, judgeship effect); they sum exactly to f2/j2 − f1/j1."""
    filings = (f2 - f1) * (1 / j1 + 1 / j2) / 2
    judgeships = (f1 + f2) / 2 * (1 / j2 - 1 / j1)
    return filings, judgeships


# ── IDB counts ───────────────────────────────────────────────────────────────

_COUNT_SQL = {
    "filed": (
        "SELECT court, coalesce(nos_group, 'Unknown'), filing_fy, count(*) "
        "FROM idb.idb_civil WHERE filing_fy IN (?, ?) AND list_contains(?, court) "
        "GROUP BY ALL"
    ),
    "terminated": (
        "SELECT court, coalesce(nos_group, 'Unknown'), termination_fy, count(*) "
        "FROM idb.idb_civil_terminations WHERE termination_fy IN (?, ?) "
        "AND list_contains(?, court) GROUP BY ALL"
    ),
}
_PENDING_SQL = (
    "SELECT court, coalesce(nos_group, 'Unknown'), count(*) FROM idb.idb_civil_record "
    "WHERE " + PENDING_WHERE + " AND list_contains(?, court) GROUP BY ALL"
)
_MDL_SQL = {
    "filed": (
        "SELECT court, coalesce(mdl_docket, '?'), filing_fy, count(*) "
        "FROM idb.idb_civil WHERE filing_fy IN (?, ?) "
        "AND list_contains(?, court) AND is_mdl_direct_filed "
        "GROUP BY ALL"
    ),
    "terminated": (
        "SELECT court, coalesce(mdl_docket, '?'), termination_fy, count(*) "
        "FROM idb.idb_civil_terminations WHERE termination_fy IN (?, ?) "
        "AND list_contains(?, court) AND (is_mdl_direct_filed OR is_mdl_transferred) "
        "GROUP BY ALL"
    ),
}
_MDL_PENDING_SQL = (
    "SELECT court, coalesce(mdl_docket, '?'), count(*) FROM idb.idb_civil_record "
    "WHERE " + PENDING_WHERE + " AND list_contains(?, court) "
    "AND (is_mdl_direct_filed OR is_mdl_transferred) GROUP BY ALL"
)

Cells = dict[tuple[str, str], float]


def _idb_cells(
    db: Database, rule: str, districts: list[str], a: int, b: int, mdl: bool = False
) -> tuple[Cells, Cells]:
    before: Cells = defaultdict(float)
    after: Cells = defaultdict(float)
    if rule == "pending":
        sql = _MDL_PENDING_SQL if mdl else _PENDING_SQL
        for fy, target in ((a, before), (b, after)):
            d = date(fy, 9, 30)
            for court, key, n in db.rows(sql, [d, d, d, districts]):
                target[(court, key)] += n
        return before, after
    sql = (_MDL_SQL if mdl else _COUNT_SQL)[rule]
    for court, key, fy, n in db.rows(sql, [a, b, districts]):
        (before if fy == a else after)[(court, key)] += n
    return before, after


def _collapse(cells: Cells, index: int) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for k, v in cells.items():
        out[k[index]] += v
    return out


# ── drivers ──────────────────────────────────────────────────────────────────


def _pandemic(a: int, b: int) -> Driver | None:
    if not (set(range(a, b + 1)) & PANDEMIC_FYS):
        return None
    return Driver(
        code="pandemic_window",
        title="Pandemic period",
        basis="context",
        evidence=(
            "The window includes FY2020–FY2021: courts limited in-person proceedings "
            "and jury trials from March 2020 (national emergency declared March 13, "
            "2020). Attribute a change to the pandemic only where the breakdown "
            "supports it."
        ),
    )


def _data_breaks(db: Database, a: int, b: int, groups: Iterable[str]) -> list[Driver]:
    if not db.has_idb:
        return []
    rows = db.rows(
        "SELECT id, field, codes, summary, detail FROM idb.data_breaks "
        "WHERE date > CAST(? AS DATE) AND date <= CAST(? AS DATE) "
        "AND id NOT IN ('release-snapshot', 'pandemic-2020')",
        # From the start of FY a: a break during FY a already splits that year.
        [f"{a - 1}-09-30", f"{b}-09-30"],
    )
    from courts_analyst.core.enums import nos_entry

    wanted = set(groups)
    out = []
    for bid, field, codes, summary, detail in rows:
        if field == "nos" and not any(
            (e := nos_entry(c)) and e.get("group") in wanted for c in codes or []
        ):
            continue
        out.append(
            Driver(
                code="data_break",
                title=summary,
                basis="context",
                evidence=f"{detail} ({bid})",
            )
        )
    return out


def _revision_drivers(
    db: Database, m: Measure, court: str, a: int, b: int
) -> tuple[list[Driver], list[Caveat]]:
    drivers: list[Driver] = []
    warnings: list[Caveat] = []
    for fy in (a, b):
        chain = load_chain(db, m.id, court, fy)
        notes, note_warnings = revision_notes(db, m, court, fy, chain)
        warnings += note_warnings
        for n in notes:
            inferred = n.basis == "inferred"
            drivers.append(
                Driver(
                    code="methodology_revision",
                    title=(
                        f"Inference: {_name(n.district or '')} accounts for most of "
                        f"the FY{fy} revision"
                        if inferred
                        else f"FY{fy} figure revised between editions"
                    ),
                    basis=n.basis,
                    evidence=n.text,
                    magnitude=-(n.points or 0) if inferred else n.revision,
                    share_of_change=(
                        (n.points or 0) / abs(n.revision)
                        if inferred and n.revision
                        else None
                    ),
                )
            )
    return drivers, warnings


def _mdl_driver(
    db: Database, rule: str, districts: list[str], a: int, b: int, total: float
) -> Driver | None:
    before, after = _idb_cells(db, rule, districts, a, b, mdl=True)
    delta = sum(after.values()) - sum(before.values())
    if not before and not after:
        return None
    share = delta / total if total else None
    if abs(delta) < 1000 and (share is None or abs(share) < 0.25):
        return None
    cells = contributions(
        {f"{k[0]}|{k[1]}": v for k, v in before.items()},
        {f"{k[0]}|{k[1]}": v for k, v in after.items()},
        limit=3,
        small_cells=True,
    )
    top = [
        f"{_name(k[0])} MDL {k[1]} {c.change:+,.0f}"
        for c in cells
        if c.key != "__other__"
        for k in [_split(c.key)]
    ]
    what = {
        "filed": "directly filed MDL cases",
        "terminated": "terminations of MDL cases (direct-filed or transferred)",
        "pending": "pending MDL cases (direct-filed or transferred)",
    }[rule]
    return Driver(
        code="mdl_direct_filed" if rule == "filed" else "mdl_cases",
        title="Multidistrict litigation"
        if rule != "filed"
        else "Directly filed MDL cases",
        basis="idb_derived",
        evidence=f"{what[0].upper() + what[1:]} changed by {delta:+,.0f}"
        + ("" if share is None or abs(share) > 3 else f" ({share:.0%} of the change)")
        + "; largest: "
        + "; ".join(top)
        + ".",
        magnitude=delta,
        share_of_change=share,
    )


def _split(key: str) -> tuple[str, str]:
    court, _, rest = key.partition("|")
    return court, rest


def _pair_contributions(before: Cells, after: Cells) -> list[Contribution]:
    b2 = {f"{k[0]}|{k[1]}": v for k, v in before.items()}
    a2 = {f"{k[0]}|{k[1]}": v for k, v in after.items()}
    labels = {k: f"{_name(_split(k)[0])} · {_split(k)[1]}" for k in set(b2) | set(a2)}
    return contributions(b2, a2, labels, small_cells=True)


# ── entry point ──────────────────────────────────────────────────────────────


@guarded
def explain_change(
    db: Database,
    measure: str,
    court: str = "US",
    period_from: int = 2019,
    period_to: int = 2020,
) -> Result[ChangeExplanation]:
    """Explain the change in ``measure`` for ``court`` between two fiscal years."""
    m = get_measure(measure)
    if period_from >= period_to:
        raise InvalidCohortError("period_from must be earlier than period_to.")
    if court not in COURTS:
        from courts_analyst.core.errors import UnknownCourtError

        raise UnknownCourtError(f"Unknown court {court!r}.")
    if m.idb:
        return _explain_count(db, m, court, period_from, period_to)
    if m.family == "per_judgeship":
        return _explain_per_judgeship(db, m, court, period_from, period_to)
    raise OutOfScopeError(
        f"explain_change can decompose civil filings, terminations, pending cases "
        f"and filings per judgeship; not {m.label}.",
        ["get_official_figure for each year"],
    )


def _headline(m: Measure, court: str, a: int, b: int, change: float, lead: str) -> str:
    direction = "rose" if change > 0 else "fell" if change < 0 else "was unchanged"
    amount = f" by {abs(change):,.0f}" if change else ""
    return (
        f"{m.label} for {_name(court)} {direction}{amount} from FY{a} to FY{b}. {lead}"
    )


def _explain_count(
    db: Database, m: Measure, court: str, a: int, b: int
) -> Result[ChangeExplanation]:
    vintage = choose_vintage(
        {a: _need_chain(db, m, court, a), b: _need_chain(db, m, court, b)},
        "latest",
        measure=m.id,
    )
    first, second = vintage.points[a], vintage.points[b]
    official_change = second.shown - first.shown
    warnings: list[Caveat] = list(vintage.warnings)
    provenance: list[Provenance] = [
        Provenance(
            source="official_table",
            table_code=r.table_code,
            series=series_title(r.edition),
            edition=r.edition,
            period=Period.for_end(fy, r.period_end),
            definition=m.definition,
            url=r.url,
            cell_ref=r.cell_ref,
        )
        for fy, r in ((a, first), (b, second))
    ]
    data: dict[str, Any] = {}
    drivers: list[Driver] = []
    lead = ""
    if db.has_idb:
        districts = expand_courts([court])
        assert m.idb is not None
        before, after = _idb_cells(db, m.idb, districts, a, b)
        idb_a, idb_b = int(sum(before.values())), int(sum(after.values()))
        idb_change = idb_b - idb_a
        by_type = contributions(
            _collapse(before, 1), _collapse(after, 1), small_cells=True
        )
        by_district = (
            contributions(
                _collapse(before, 0),
                _collapse(after, 0),
                {d: _name(d) for d in districts},
                small_cells=True,
            )
            if len(districts) > 1
            else []
        )
        pairs = _pair_contributions(before, after)
        data.update(
            idb_from=idb_a,
            idb_to=idb_b,
            idb_change=idb_change,
            by_case_type=by_type,
            by_district=by_district,
            by_district_and_case_type=pairs,
        )
        mdl = _mdl_driver(db, m.idb, districts, a, b, idb_change)
        if mdl:
            drivers.append(mdl)
        if m.idb == "filed":
            mb, ma = _idb_cells(db, "filed", districts, a, b, mdl=True)
            data["idb_change_excluding_mdl_direct"] = int(
                idb_change - (sum(ma.values()) - sum(mb.values()))
            )
        gap = official_change - idb_change
        if official_change and abs(gap) > max(0.02 * abs(official_change), 50):
            warnings.append(
                Caveat(
                    code="inexact_match",
                    message=f"The IDB rebuilds a change of {idb_change:+,} against "
                    f"the official {official_change:+,.0f}; breakdowns explain the "
                    "IDB change (see reconcile for why the counts differ).",
                )
            )
        tops = [c for c in (by_district or pairs) if c.key_contributor][:3]
        if tops:
            lead = (
                "Largest contributors (IDB): "
                + "; ".join(f"{c.label} {c.change:+,.0f}" for c in tops)
                + "."
            )
        provenance.append(
            idb_provenance(
                db,
                f"{m.label} rebuilt from IDB records and split by district and "
                "nature-of-suit group.",
            )
        )
        series = (
            f"Totals: Table C-1 ({first.edition}, {second.edition}). Breakdowns: "
            "FJC IDB civil records."
        )
    else:
        districts = expand_courts([court])
        if len(districts) > 1:
            w: dict[str, dict[str, float]] = {"a": {}, "b": {}}
            for fy, ed, slot in (
                (a, first.edition, "a"),
                (b, second.edition, "b"),
            ):
                for code, val in db.rows(
                    "SELECT v.court, v.value FROM cat.observation v "
                    "WHERE v.measure_id = ? AND v.fiscal_year = ? "
                    "AND v.edition = ? AND list_contains(?, v.court)",
                    [m.id, fy, ed, districts],
                ):
                    w[slot][code] = float(val)
            if w["a"] and w["b"]:
                district_sum_change = sum(w["b"].values()) - sum(w["a"].values())
                remainder = official_change - district_sum_change
                if abs(remainder) > 1e-9:
                    w["b"]["__rounding__"] = w["b"].get("__rounding__", 0.0) + remainder
                labels: dict[str, str] = {d: _name(d) for d in districts} | {
                    "__rounding__": "Unallocated (rounding in published values)"
                }
                by_district = contributions(w["a"], w["b"], labels)
                data["by_district"] = by_district
                tops = [c for c in by_district if c.key_contributor][:3]
                if tops:
                    lead = (
                        "Largest contributors (official district rows): "
                        + "; ".join(f"{c.label} {c.change:+,.0f}" for c in tops)
                        + "."
                    )
                series = (
                    f"Table C-1 ({first.edition}, {second.edition}), district rows; "
                    "no case-type breakdown."
                )
                warnings.append(
                    Caveat(
                        code="out_of_scope",
                        message=(
                            "The IDB isn't loaded: the district split comes from the "
                            "official tables; a case-type or MDL breakdown needs "
                            "the IDB."
                        ),
                    )
                )
            else:
                series = f"Table C-1 ({first.edition}, {second.edition}); no breakdown."
                warnings.append(
                    Caveat(
                        code="out_of_scope",
                        message=(
                            "The IDB isn't loaded, so the change can't be broken down."
                        ),
                    )
                )
        else:
            series = f"Table C-1 ({first.edition}, {second.edition}); no breakdown."
            warnings.append(
                Caveat(
                    code="out_of_scope",
                    message="The IDB isn't loaded, so the change can't be broken down.",
                )
            )
    if (p := _pandemic(a, b)) is not None:
        drivers.append(p)
    rev, rev_warn = _revision_drivers(db, m, court, a, b)
    drivers += rev
    warnings += rev_warn
    groups = [c.key for c in data.get("by_case_type", []) if c.key_contributor]
    breaks = _data_breaks(db, a, b, groups)
    drivers += breaks
    warnings += [
        Caveat(
            code="data_break",
            message=f"The window crosses a data break: {d.title} "
            f"({d.evidence.rsplit('(', 1)[-1]}",
        )
        for d in breaks
    ]
    court_obj = COURTS[court]
    result = ChangeExplanation(
        measure=m.id,
        measure_label=m.label,
        unit=m.unit,
        court=court,
        court_name=court_obj.citation or court_obj.name,
        period_from=a,
        period_to=b,
        mode="count",
        headline=_headline(m, court, a, b, official_change, lead),
        official_from=first.ref(),
        official_to=second.ref(),
        official_change=official_change,
        official_change_pct=(official_change / first.shown if first.shown else None),
        decomposition_series=series,
        drivers=drivers,
        **data,
    )
    return ok(result, provenance, warnings, _next(court, m, a, b))


def _next(court: str, m: Measure, a: int, b: int) -> list[str]:
    out = [f"reconcile(measure='{m.id}', court='{court}', fiscal_year={b})"]
    if m.idb == "filed":
        out.append(
            f"find_cases(courts=['{court}'], fy_from={b}, fy_to={b}) to drill into a "
            "contributor"
        )
    return out


def _explain_per_judgeship(
    db: Database, m: Measure, court: str, a: int, b: int
) -> Result[ChangeExplanation]:
    ca = _need_chain(db, m, court, a)
    cb = _need_chain(db, m, court, b)
    # The first-published Judicial Business series is the one with districts;
    # when a year predates it (1990 is JFF-only), one JFF edition printing
    # both years keeps the pair in one series.
    vintage = choose_vintage({a: ca, b: cb}, "first_published", measure=m.id)
    fa, fb = vintage.points[a], vintage.points[b]
    with_districts = fa.edition.startswith("JB") and fb.edition.startswith("JB")
    ja = _need_chain(db, get_measure("authorized_judgeships"), court, a)
    jb = _need_chain(db, get_measure("authorized_judgeships"), court, b)
    j1 = next((r.value for r in ja if r.edition == fa.edition), ja[0].value)
    j2 = next((r.value for r in jb if r.edition == fb.edition), jb[0].value)
    f1, f2 = fa.value * j1, fb.value * j2
    filings_eff, judge_eff = shift_share(f1, j1, f2, j2)
    change = fb.value - fa.value
    warnings: list[Caveat] = list(vintage.warnings)
    drivers: list[Driver] = []
    by_district: list[Contribution] = []
    if COURTS[court].level is not CourtLevel.DISTRICT and with_districts:
        districts = expand_courts([court])
        scale = (1 / j1 + 1 / j2) / 2
        w: dict[str, dict[str, float]] = {"a": {}, "b": {}}
        for fy, ed, slot in ((a, fa.edition, "a"), (b, fb.edition, "b")):
            for code, val in db.rows(
                "SELECT v.court, v.value * j.value FROM cat.observation v "
                "JOIN cat.observation j ON j.court = v.court "
                "AND j.fiscal_year = v.fiscal_year AND j.edition = v.edition "
                "AND j.measure_id = 'authorized_judgeships' "
                "WHERE v.measure_id = ? AND v.fiscal_year = ? AND v.edition = ? "
                "AND list_contains(?, v.court)",
                [m.id, fy, ed, districts],
            ):
                w[slot][code] = float(val) * scale
        # District rows (in points of the filings effect) plus an exact
        # remainder, so the breakdown sums to the filings effect.
        remainder = filings_eff - (sum(w["b"].values()) - sum(w["a"].values()))
        if abs(remainder) > 1e-9:
            w["b"]["__rounding__"] = remainder
        labels = {d: _name(d) for d in districts} | {
            "__rounding__": "Unallocated (rounding in published values)"
        }
        by_district = contributions(w["a"], w["b"], labels)
        by_district = [
            c.model_copy(
                update={"share_of_change": c.change / change if change else None}
            )
            for c in by_district
        ]
        _mark_key(by_district, filings_eff)
    if abs(judge_eff) >= 0.5:
        drivers.append(
            Driver(
                code="judgeship_change",
                title="Change in authorized judgeships",
                basis="official",
                evidence=f"Authorized judgeships {j1:g} (FY{a}) → {j2:g} (FY{b}) "
                f"moved the figure by {judge_eff:+.1f}.",
                magnitude=judge_eff,
                share_of_change=judge_eff / change if change else None,
            )
        )
    if (m.id.startswith("civil") or m.id.startswith("weighted_civil")) and db.has_idb:
        districts = expand_courts([court])
        # Shares only make sense against case counts, not weighted filings.
        mdl = _mdl_driver(db, "filed", districts, a, b, 0 if m.weighted else f2 - f1)
        if mdl:
            drivers.append(mdl)
    if (p := _pandemic(a, b)) is not None:
        drivers.append(p)
    rev, rev_warn = _revision_drivers(db, m, court, a, b)
    drivers += rev
    warnings += rev_warn
    if ca[-1].shown != fa.shown or cb[-1].shown != fb.shown:
        warnings.append(
            Caveat(
                code="revised_figure",
                message=(
                    f"The breakdown uses {fa.edition}: {fmt(fa.shown)} and "
                    f"{fb.edition}: {fmt(fb.shown)}"
                    + (
                        ", the first-published series (the only one with district "
                        "rows). "
                        if with_districts
                        else ", one series for both years. "
                    )
                    + "The current official figures are "
                    f"{ca[-1].shown:g} ({ca[-1].edition}) and {cb[-1].shown:g} "
                    f"({cb[-1].edition})."
                ),
            )
        )
    tops = [c for c in by_district if c.key_contributor][:3]
    lead = (
        "Largest contributors: "
        + "; ".join(f"{c.label} {c.change:+,.0f}" for c in tops)
        + "."
        if tops
        else ""
    )
    court_obj = COURTS[court]
    result = ChangeExplanation(
        measure=m.id,
        measure_label=m.label,
        unit=m.unit,
        court=court,
        court_name=court_obj.citation or court_obj.name,
        period_from=a,
        period_to=b,
        mode="per_judgeship",
        headline=_headline(m, court, a, b, round_half_up(change, 0), lead),
        official_from=fa.ref(),
        official_to=fb.ref(),
        official_change=fb.shown - fa.shown,
        official_change_pct=(change / fa.value if fa.value else None),
        filings_effect=filings_eff,
        judgeship_effect=judge_eff,
        decomposition_series=(
            f"First-published Table X-1A ({fa.edition}, {fb.edition}): district "
            "value × district judgeships; exact shift-share split."
            if with_districts
            else f"{fa.edition} national values for both years (no district rows "
            "in that series); exact shift-share split."
        ),
        by_district=by_district,
        drivers=drivers,
    )
    provenance = [
        Provenance(
            source="official_table",
            table_code=r.table_code,
            series=series_title(r.edition),
            edition=r.edition,
            period=Period.for_end(fy, r.period_end),
            definition=m.definition,
            url=r.url,
            cell_ref=r.cell_ref,
            revision_status="revised" if len({x.shown for x in ch}) > 1 else None,
            first_published=ch[0].ref(),
            later_revisions=[x.ref() for x in ch[1:] if x.shown != ch[0].shown][:1],
        )
        for fy, r, ch in ((a, fa, ca), (b, fb, cb))
    ]
    return ok(result, provenance, warnings)
