"""Table families: how to turn one official table's :class:`Grid` into observations.

A *family* is one table code in one series (JB X-1A, JFF 6.2, …) across all
its editions. Each family says:

- which row labels it expects (courts or fiscal years),
- how printed column headers map to measure ids (regex rules on the
  normalised header path, so reordered or renamed columns still map),
- which headers are *group* headers in the PDF layout,
- which measures every edition must have (a missing one is header drift we
  haven't handled, and fails the parse instead of silently dropping data).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from courts_analyst.core.courts import COURTS, UnknownCourtError, resolve_court
from courts_analyst.pipeline.tables.grid import (
    MARKERS,
    Grid,
    GridError,
    normalize_header,
    read_pdf,
    read_xlsx,
)
from courts_analyst.pipeline.tables.records import (
    Footnote,
    Observation,
    Series,
    SourceFile,
)

RowKind = Literal["court", "year"]


class HeaderDriftError(GridError):
    """An edition's headers didn't map to the measures the family requires."""


@dataclass(frozen=True, slots=True)
class Rule:
    """``pattern`` is searched in the normalised header path.

    A named group ``fy`` in the pattern takes the fiscal year from the header
    itself (C-1 before 2023 prints "Pending September 30, 2019" next to the
    2020 columns); otherwise the row or the edition gives the year.
    """

    measure_id: str
    pattern: str


@dataclass(frozen=True)
class Family:
    key: str
    series: Series
    table_code: str
    stem: str
    """File-name stem on uscourts.gov, e.g. ``jb_x1a``."""
    number_slug: str
    """Slug of the /data-table-numbers/<slug> listing page, e.g. ``x-1a``."""
    title: str
    description: str
    row_kind: RowKind
    rules: tuple[Rule, ...]
    required: frozenset[str]
    group_headers: tuple[str, ...] = ()
    group_fit: Literal["midpoint", "centered"] = "midpoint"
    """How PDF group headers span columns (see grid._pdf_headers)."""
    first_edition: int = 2016
    stretch: bool = False
    ignore_headers: tuple[str, ...] = field(default=())

    def rule_for(self, header: str) -> tuple[str, int | None] | None:
        """``(measure_id, fiscal_year_from_header)`` for a printed header."""
        norm = normalize_header(header)
        if any(re.search(p, norm) for p in self.ignore_headers):
            return None
        for rule in self.rules:
            m = re.search(rule.pattern, norm)
            if m:
                fy = m.groupdict().get("fy")
                return rule.measure_id, int(fy) if fy else None
        return None


# Shared rules for the two per-judgeship tables (X-1A and 6.2).
_PER_JUDGESHIP = (
    Rule("authorized_judgeships", r"^(authorized )?judgeships?$"),
    Rule("civil_filings_per_judgeship", r"^unweighted filings per judgeship civil$"),
    Rule(
        "criminal_filings_per_judgeship", r"^unweighted filings per judgeship criminal$"
    ),
    Rule(
        "supervision_hearings_per_judgeship",
        r"^unweighted filings per judgeship supervis\w*( release)? hearings$",
    ),
    Rule("total_filings_per_judgeship", r"^unweighted filings per judgeship total$"),
    Rule(
        "weighted_civil_filings_per_judgeship",
        r"^weighted filings per judgeship civil$",
    ),
    Rule(
        "weighted_criminal_filings_per_judgeship",
        r"^weighted filings per judgeship criminal$",
    ),
    Rule(
        "weighted_supervision_hearings_per_judgeship",
        r"^weighted filings per judgeship supervis\w*( release)? hearings$",
    ),
    Rule(
        "weighted_total_filings_per_judgeship",
        r"^weighted filings per judgeship total$",
    ),
)
_PER_JUDGESHIP_GROUPS = (r"weighted filings per judgeship",)
_PER_JUDGESHIP_TITLE = (
    "U.S. District Courts—Weighted and Unweighted Filings per Authorized Judgeship"
)

# 2023+ prints "Total | Filed"; earlier editions "Total Civil Cases | Commenced"
# and add a "Pending September 30, <prior year>" column.
_C1 = (
    *(
        Rule(f"{prefix}civil_cases_{what}", rf"^{group}( civil)? cases {verb}$")
        for prefix, group in (("", "total"), ("us_", "us"), ("private_", "private"))
        for what, verb in (
            ("pending", r"pending sept(ember)? 3[01] (?P<fy>\d{4})( \d)?"),
            ("filed", "(filed|commenced)"),
            ("terminated", "terminated"),
            ("pending", "pending"),
        )
    ),
    Rule("civil_cases_filed", r"^total (filed|commenced)$"),
    Rule("civil_cases_terminated", r"^total terminated$"),
    Rule("civil_cases_pending", r"^total pending$"),
)

_C5 = (
    Rule("civil_cases_terminated_for_median", r"^total cases number of cases$"),
    Rule("civil_median_months_to_disposition", r"^total cases median"),
    Rule("civil_cases_no_court_action", r"^no court action number of cases$"),
    Rule("civil_median_months_no_court_action", r"^no court action median"),
    Rule(
        "civil_cases_court_action_before_pretrial", r"before pretrial number of cases$"
    ),
    Rule("civil_median_months_court_action_before_pretrial", r"before pretrial median"),
    Rule(
        "civil_cases_court_action_during_after_pretrial",
        r"during or after pretrial number of cases$",
    ),
    Rule(
        "civil_median_months_court_action_during_after_pretrial",
        r"during or after pretrial median",
    ),
    Rule("civil_cases_court_action_trial", r"(during )?trial number of cases$"),
    Rule("civil_median_months_court_action_trial", r"(during )?trial median"),
)

# "Court Action" spans three columns but is centred over one, so the PDF can't
# say which it covers: the rules treat it as optional.
_J63 = (
    Rule("civil_median_months_to_disposition", r"^civil overall( civil)? median"),
    Rule("civil_median_months_no_court_action", r"^civil no court action$"),
    Rule(
        "civil_median_months_court_action_before_pretrial",
        r"^civil( court action)? before pretrial$",
    ),
    Rule(
        "civil_median_months_court_action_during_after_pretrial",
        r"^civil( court action)? during or after pretrial$",
    ),
    Rule(
        "civil_median_months_court_action_trial",
        r"^civil( court action)? (during )?trial$",
    ),
    Rule("criminal_median_months_to_disposition", r"^criminal all defendants$"),
    Rule("criminal_median_months_dismissed", r"^criminal dismissed$"),
    Rule("criminal_median_months_guilty_plea", r"^criminal guilty plea$"),
    Rule("criminal_median_months_bench_trial", r"^criminal bench trial$"),
    Rule("criminal_median_months_jury_trial", r"^criminal jury trial$"),
)

_J61 = (
    Rule("authorized_judgeships_incl_territorial", r"^authorized judgeships?$"),
    Rule("total_cases_filed", r"caseload filed$|^filed$"),
    Rule("total_cases_terminated", r"caseload terminated$|^terminated$"),
    Rule("total_cases_pending", r"caseload pending$|^pending$"),
)

FAMILIES: dict[str, Family] = {
    f.key: f
    for f in (
        Family(
            key="jb_x1a",
            series=Series.JB,
            table_code="X-1A",
            stem="jb_x1a",
            number_slug="x-1a",
            title=_PER_JUDGESHIP_TITLE,
            description=(
                "Per-district filings per authorized judgeship, raw and weighted "
                "by FJC case weights, for the 12 months ending September 30. First "
                "publication of each year's weighted figures."
            ),
            row_kind="court",
            rules=_PER_JUDGESHIP,
            required=frozenset(r.measure_id for r in _PER_JUDGESHIP),
            group_headers=_PER_JUDGESHIP_GROUPS,
        ),
        Family(
            key="jff_6.2",
            series=Series.JFF,
            table_code="6.2",
            stem="jff_6.2",
            number_slug="62",
            title=_PER_JUDGESHIP_TITLE,
            description=(
                "National multi-year series of filings per authorized judgeship, "
                "raw and weighted. Later editions revise earlier years."
            ),
            row_kind="year",
            rules=_PER_JUDGESHIP,
            required=frozenset(r.measure_id for r in _PER_JUDGESHIP),
            group_headers=_PER_JUDGESHIP_GROUPS,
        ),
        Family(
            key="jb_c1",
            series=Series.JB,
            table_code="C-1",
            stem="jb_c1",
            number_slug="c-1",
            title="U.S. District Courts—Civil Cases Commenced, Terminated, and Pending",
            description=(
                "Civil cases filed, terminated and pending by circuit and district, "
                "split into U.S.-party and private cases, for the 12 months ending "
                "September 30."
            ),
            row_kind="court",
            rules=_C1,
            required=frozenset(r.measure_id for r in _C1),
            group_headers=(
                r"^total( civil cases)?$",
                r"^u\.?s\.?( civil)? cases$",
                r"^private( civil)? cases$",
            ),
        ),
        Family(
            key="jb_c5",
            series=Series.JB,
            table_code="C-5",
            stem="jb_c5",
            number_slug="c-5",
            title=(
                "U.S. District Courts—Median Time Intervals From Filing to "
                "Disposition of Civil Cases Terminated, by District and Method of "
                "Disposition"
            ),
            description="Civil disposition counts and median months, by district "
            "and method.",
            row_kind="court",
            rules=_C5,
            required=frozenset(
                {
                    "civil_cases_terminated_for_median",
                    "civil_median_months_to_disposition",
                }
            ),
            group_headers=(
                r"^total cases$",
                r"^no court action$",
                r"^court action$",
                r"^before pretrial$",
                r"^during or after pretrial$",
                r"^(during )?trial$",
            ),
            group_fit="centered",
        ),
        Family(
            key="jff_6.1",
            series=Series.JFF,
            table_code="6.1",
            stem="jff_6.1",
            number_slug="61",
            title=(
                "U.S. District Courts—Total Civil and Criminal Cases Filed, "
                "Terminated, and Pending (Including Transfers)"
            ),
            description="National multi-year totals for civil plus criminal caseload.",
            row_kind="year",
            rules=_J61,
            required=frozenset(r.measure_id for r in _J61),
            group_headers=(r"district court caseload",),
        ),
        Family(
            key="jff_6.3",
            series=Series.JFF,
            table_code="6.3",
            stem="jff_6.3",
            number_slug="63",
            title=(
                "U.S. District Courts—Median Time Intervals From Filing to "
                "Disposition for Civil Cases and Criminal Defendants"
            ),
            description="National multi-year median disposition times, civil and "
            "criminal.",
            row_kind="year",
            rules=_J63,
            required=frozenset(
                {
                    "civil_median_months_to_disposition",
                    "criminal_median_months_to_disposition",
                }
            ),
            group_headers=(r"^civil$", r"^criminal$"),
        ),
    )
}


# ── Row labels ──────────────────────────────────────────────────────────────

_YEAR = re.compile(r"^(19|20)\d\d$")


def court_code(label: str) -> str | None:
    """Canonical court code for a row label, or None if it isn't a court."""
    try:
        return resolve_court(label).code
    except UnknownCourtError:
        return None


def row_test(kind: RowKind) -> Callable[[str], bool]:
    if kind == "year":
        return lambda label: bool(_YEAR.match(label))
    return lambda label: court_code(label) is not None


# ── Footnotes ───────────────────────────────────────────────────────────────

_MARKER_START = re.compile(rf"^\s*([{re.escape(MARKERS)}])\s*(.+)$", re.S)


def split_footnotes(notes: list[str]) -> list[tuple[str | None, str]]:
    """Notes → ``(marker, text)``; marker is None for general notes and sources."""
    out: list[tuple[str | None, str]] = []
    for note in notes:
        for line in re.split(r"\n+", note):
            line = " ".join(line.split())
            if not line:
                continue
            m = _MARKER_START.match(line)
            if m:
                out.append((m.group(1), m.group(2).strip()))
            elif (
                out
                and out[-1][0] is None
                and not re.match(r"^(note|source)", line, re.I)
            ):
                out[-1] = (None, f"{out[-1][1]} {line}")
            else:
                out.append((None, line))
    return out


# ── Parse ───────────────────────────────────────────────────────────────────


@dataclass
class ParseResult:
    observations: list[Observation]
    footnotes: list[Footnote]
    title: str
    warnings: list[str]
    unmapped_headers: list[str]


def read_grid(family: Family, path: Path) -> Grid:
    test = row_test(family.row_kind)
    if path.suffix.lower() == ".xlsx":
        return read_xlsx(path, test)
    if path.suffix.lower() == ".pdf":
        return read_pdf(path, test, family.group_headers, family.group_fit)
    raise GridError(f"unsupported format: {path.name}")


def parse(family: Family, source: SourceFile, path: Path) -> ParseResult:
    """Parse one downloaded file into observations with footnotes attached."""
    grid = read_grid(family, path)
    col_rule = [family.rule_for(h) for h in grid.headers]
    col_measure = [r[0] if r else None for r in col_rule]
    mapped = {m for m in col_measure if m}
    missing = family.required - mapped
    if missing:
        raise HeaderDriftError(
            f"{source.file_id}: headers {grid.headers!r} don't cover {sorted(missing)}"
        )
    dupes = {r for r in col_rule if r and col_rule.count(r) > 1}
    if dupes:
        raise HeaderDriftError(
            f"{source.file_id}: several columns map to {sorted(dupes)}"
        )
    unmapped = [h for h, m in zip(grid.headers, col_measure, strict=True) if not m]
    for pno, page in enumerate(grid.page_headers[1:], start=2):
        if [family.rule_for(h) for h in page] != col_rule:
            raise HeaderDriftError(
                f"{source.file_id}: header on page {pno} maps differently: {page!r}"
            )

    footnotes: list[Footnote] = []
    by_marker: dict[str, str] = {}
    for i, (marker, text) in enumerate(split_footnotes(grid.notes), start=1):
        fid = f"{source.file_id}:n{i}"
        footnotes.append(
            Footnote(footnote_id=fid, file_id=source.file_id, marker=marker, text=text)
        )
        if marker and marker not in by_marker:
            by_marker[marker] = fid

    warnings: list[str] = []

    def ids(markers: tuple[str, ...], where: str) -> tuple[str, ...]:
        out = []
        for mk in markers:
            if mk in by_marker:
                out.append(by_marker[mk])
            else:
                warnings.append(f"{where}: marker {mk!r} has no footnote text")
        return tuple(dict.fromkeys(out))

    header_fn = [
        ids(tuple(re.findall(f"[{re.escape(MARKERS)}]", h)), h) for h in grid.headers
    ]

    observations: list[Observation] = []
    seen: set[tuple[str, str, int]] = set()
    for row in grid.rows:
        row_fn = ids(row.label_markers, row.label_ref)
        if family.row_kind == "court":
            code = court_code(row.label)
            assert code is not None
            fy = source.period_end.year
            period_end = source.period_end
        else:
            code = "US"
            fy = int(row.label)
            june = any(
                "june 30" in f.text.lower()
                for f in footnotes
                if f.footnote_id in row_fn
            )
            period_end = date(fy, 6, 30) if june else date(fy, 9, 30)
        for ci, cell in enumerate(row.cells):
            rule = col_rule[ci]
            if rule is None or cell is None:
                continue
            measure, header_fy = rule
            obs_fy, obs_end = fy, period_end
            if header_fy is not None and header_fy != fy:
                obs_fy, obs_end = header_fy, date(header_fy, 9, 30)
            key = (measure, code, obs_fy)
            if key in seen:
                warnings.append(f"{row.label_ref}: duplicate {key}; kept the first")
                continue
            seen.add(key)
            observations.append(
                Observation(
                    file_id=source.file_id,
                    measure_id=measure,
                    court=code,
                    fiscal_year=obs_fy,
                    period_end=obs_end,
                    value=cell.value,
                    decimals=cell.decimals,
                    footnote_ids=tuple(
                        dict.fromkeys(
                            header_fn[ci] + row_fn + ids(cell.markers, cell.ref)
                        )
                    ),
                    cell_ref=cell.ref,
                    raw=cell.text,
                )
            )

    if family.row_kind == "court":
        districts = {
            o.court for o in observations if COURTS[o.court].level.value == "district"
        }
        if "US" not in {o.court for o in observations}:
            raise GridError(f"{source.file_id}: no national total row")
        if len(districts) < 90:
            warnings.append(f"{source.file_id}: only {len(districts)} districts parsed")
    return ParseResult(observations, footnotes, grid.title, warnings, unmapped)
