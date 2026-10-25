"""The verification gate: an answer is saved only if every number in it is
backed by the official data, and its figures come from consistent editions.

Rules (ADR 0013, decision 5):

1. Every cited value is exactly what that edition printed.
2. Every number in the text is a cited value, a published threshold (430,
   600), a number the server's own read tools produced when re-run for this
   answer, or a difference or percentage change between backed values.
   Fiscal years, table codes, docket numbers, dates, links and code are not
   numbers here. A number the text attributes
   to an edition ("322 (JFF-2024)") must be cited from that edition.
3. The cited figures of each measure come from one consistent set of
   editions (``guardrails.vintage``: one publication series, and no edition
   used for one figure printing another one differently). A figure quoted as
   an earlier edition's value, in a sentence that says so ("first published
   as 554", "updated the number to 322") or that quotes another edition's
   value for the same figure beside it, is history, not part of the set.
4. The text argues for no outcome.

A refusal names each number and what to write instead.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

from courts_analyst.core.chain import Row, load_chain
from courts_analyst.core.db import Database
from courts_analyst.core.desk.models import (
    CheckedCitation,
    CitationIn,
    ComputedValue,
    GateProblem,
    GateReport,
)
from courts_analyst.core.errors import CoreError
from courts_analyst.core.figures_text import (
    REVISION_WORDS,
    Mention,
    TextFigure,
    figures_in_text,
    find_editions,
)
from courts_analyst.core.guardrails.intent import advocacy_phrases
from courts_analyst.core.guardrails.vintage import series_of
from courts_analyst.core.judgeships import reference
from courts_analyst.core.measures import get_measure
from courts_analyst.core.numbers import fmt

TOLERANCE = 1e-6
YEARS = range(1980, 2036)

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
NOT_STATISTICS = re.compile(
    "|".join(
        [
            r"https?://\S+",  # URLs, including markdown link targets
            r"\]\([^)]*\)",  # markdown link targets without a scheme
            r"`[^`\n]*`",  # inline code
            r"\b\d{1,2}:\d{2}-[a-z]{2,4}-\d+",  # docket numbers (3:19-md-02885)
            r"\b\d{4}-\d{2}-\d{2}\b",  # ISO dates
            rf"\b{_MONTH}\s+\d{{1,2}}(?:,\s*\d{{4}})?",  # March 13, 2020
        ]
    )
)
"""Spans whose digits aren't statistics: links, code, docket numbers, dates."""

HISTORY_WORDS = re.compile(rf"{REVISION_WORDS.pattern}|\bupdat", re.I)
"""Wording that marks an earlier edition's value as history."""


def _same(a: float, b: float) -> bool:
    return abs(a - b) < TOLERANCE


def thresholds() -> list[float]:
    """Published thresholds an answer may quote without a citation."""
    return [float(t["value"]) for t in reference().get("thresholds", [])]


def _is_year(fig: TextFigure, text: str) -> bool:
    raw = text[fig.start : fig.end]
    return fig.value.is_integer() and int(fig.value) in YEARS and "," not in raw


def _label(c: CitationIn) -> str:
    court = "national" if c.court == "US" else c.court
    return f"FY{c.fiscal_year} {court} {c.measure.replace('_', ' ')}"


LABEL_WINDOW = 30
"""Characters after a number in which an edition still labels it."""


def _label_after(
    n: TextFigure, mentions: list[Mention], numbers: list[TextFigure]
) -> str | None:
    """The edition written right after a number ("322 (JFF-2024)", "322 in
    JFF-2024"): same sentence, within a few words, no other number between."""
    nxt = min((m.start for m in numbers if m.start > n.start), default=None)
    for m in mentions:
        if m.start < n.end or m.start - n.end > LABEL_WINDOW:
            continue
        if m.end > n.sentence[1] or (nxt is not None and nxt < m.start):
            continue
        return m.edition
    return None


class _Figure:
    """A citation with its edition chain."""

    def __init__(self, c: CitationIn, chain: list[Row], checked: CheckedCitation):
        self.c = c
        self.chain = chain
        self.checked = checked

    def row(self, edition: str) -> Row | None:
        return next((r for r in self.chain if r.edition == edition), None)


def _as_history(
    f: _Figure,
    hits: list[TextFigure],
    figures: list[_Figure],
    numbers: list[TextFigure],
    text: str,
) -> bool:
    """Every mention of an earlier edition's value says it changed, or sits in a
    sentence quoting another edition's value for the same figure."""
    if _same(f.c.value, f.checked.latest_value):
        return False
    others = [
        g.c.value
        for g in figures
        if (g.c.measure, g.c.court, g.c.fiscal_year)
        == (f.c.measure, f.c.court, f.c.fiscal_year)
        and not _same(g.c.value, f.c.value)
    ]

    def beside(n: TextFigure) -> bool:
        return any(
            m.sentence == n.sentence and any(_same(m.value, v) for v in others)
            for m in numbers
        )

    return all(
        HISTORY_WORDS.search(text[n.sentence[0] : n.sentence[1]]) or beside(n)
        for n in hits
    )


def _check_citations(
    db: Database, citations: Iterable[CitationIn], problems: list[GateProblem]
) -> list[_Figure]:
    out: list[_Figure] = []
    for c in citations:
        try:
            m = get_measure(c.measure)
            chain = load_chain(db, c.measure, c.court, c.fiscal_year)
        except CoreError as err:
            problems.append(
                GateProblem(
                    code="unknown_figure", message=err.message, number=fmt(c.value)
                )
            )
            continue
        row = next((r for r in chain if r.edition == c.edition), None)
        if row is None:
            printed = ", ".join(r.edition for r in chain) or "no edition we hold"
            problems.append(
                GateProblem(
                    code="unknown_figure",
                    message=f"{c.edition} doesn't print {_label(c)}.",
                    number=fmt(c.value),
                    fix=f"It is printed in: {printed}.",
                )
            )
            continue
        if not _same(row.shown, c.value):
            problems.append(
                GateProblem(
                    code="wrong_value",
                    message=f"{c.edition} prints {_label(c)} as {fmt(row.shown)}, "
                    f"not {fmt(c.value)}.",
                    number=fmt(c.value),
                    fix=f"Use {fmt(row.shown)} ({c.edition}).",
                )
            )
            continue
        latest = chain[-1]
        out.append(
            _Figure(
                c,
                chain,
                CheckedCitation(
                    **c.model_dump(),
                    measure_label=m.label,
                    table_code=row.table_code,
                    latest_value=latest.shown,
                    latest_edition=latest.edition,
                    revised=len({r.shown for r in chain}) > 1,
                ),
            )
        )
    return out


def _consistency(
    figures: list[_Figure], pub_order: dict[str, int], text_of: dict[int, str]
) -> list[GateProblem]:
    problems: list[GateProblem] = []
    by_measure: dict[str, list[_Figure]] = {}
    for f in figures:
        if not f.checked.historical:
            by_measure.setdefault(f.c.measure, []).append(f)
    for group in by_measure.values():
        editions = Counter(f.c.edition for f in group)
        if len(editions) < 2:
            continue
        basis = max(editions, key=lambda e: (editions[e], pub_order.get(e, 0)))
        anchors = [f for f in group if f.c.edition == basis]
        for f in group:
            if f.c.edition == basis:
                continue
            in_basis = f.row(basis)
            contradicted = in_basis is not None and not _same(in_basis.shown, f.c.value)
            contradicts = any(
                (r := a.row(f.c.edition)) is not None and not _same(r.shown, a.c.value)
                for a in anchors
            )
            if (
                series_of(f.c.edition) == series_of(basis)
                and not contradicted
                and not contradicts
            ):
                continue
            number = text_of.get(id(f), fmt(f.c.value))
            message = (
                f"{number} comes from {f.c.edition}, but the other "
                f"{f.checked.measure_label.lower()} figures come from {basis}."
            )
            if in_basis is not None and contradicted:
                message += f" {basis} prints {_label(f.c)} as {fmt(in_basis.shown)}."
                fix = (
                    f"Use {fmt(in_basis.shown)} ({basis}), or say that {number} was "
                    "the first-published figure."
                )
            else:
                fix = (
                    f"Quote every figure from {basis}, or name each edition and say "
                    "that the editions differ."
                )
            problems.append(
                GateProblem(
                    code="mixed_editions", message=message, number=number, fix=fix
                )
            )
    return problems


def _not_statistics(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in NOT_STATISTICS.finditer(text)]


def _derived(values: list[float]) -> set[float]:
    """Differences and percentage changes between backed values."""
    out: set[float] = set()
    for a in values:
        for b in values:
            if a == b:
                continue
            out.add(round(abs(a - b), 6))
            if b:
                pct = abs(a - b) / abs(b) * 100
                out |= {round(pct), round(pct, 1)}
    return out


def verify(
    db: Database,
    text: str,
    citations: Iterable[CitationIn],
    computed: Mapping[float, str] | None = None,
) -> GateReport:
    """Check an answer and its citations; nothing is written here.

    ``computed`` maps numbers to the read tool whose output produced them,
    when the caller re-ran the turn's tools on the server (never values a
    client supplied)."""
    problems: list[GateProblem] = []
    if not text.strip():
        return GateReport(
            passed=False,
            problems=[GateProblem(code="empty", message="The answer is empty.")],
        )
    citations = list(citations)
    figures = _check_citations(db, citations, problems)
    reported = {fmt(c.value) for c in citations} - {fmt(f.c.value) for f in figures}
    pub_order = {r.edition: r.pub_order for f in figures for r in f.chain}
    skip = _not_statistics(text)
    numbers = [
        n
        for n in figures_in_text(text)
        if not _is_year(n, text) and not any(a <= n.start < b for a, b in skip)
    ]
    allowed = thresholds()
    computed = computed or {}

    used: list[_Figure] = []
    text_of: dict[int, str] = {}
    for f in figures:
        hits = [n for n in numbers if _same(n.value, f.c.value)]
        if not hits:
            continue  # cited but not quoted: not saved
        used.append(f)
        text_of[id(f)] = text[hits[0].start : hits[0].end]
        f.checked.historical = _as_history(f, hits, figures, numbers, text)

    differences = {
        round(abs(a.c.value - b.c.value), 6)
        for a in used
        for b in used
        if a is not b and a.c.measure == b.c.measure
    }
    # Percentages and differences derive from the numbers this answer uses.
    backed = [f.c.value for f in used] + [
        n.value for n in numbers if any(_same(n.value, v) for v in computed)
    ]
    derived = _derived(backed[:60])
    computed_hits: list[ComputedValue] = []
    for n in numbers:
        if any(_same(n.value, f.c.value) for f in used):
            continue
        if any(_same(n.value, t) for t in allowed):
            continue
        if round(n.value, 6) in differences:
            continue
        hit = next((src for v, src in computed.items() if _same(n.value, v)), None)
        if hit is not None:
            computed_hits.append(
                ComputedValue(number=text[n.start : n.end], source=hit)
            )
            continue
        if round(n.value, 6) in derived or round(n.value, 1) in derived:
            continue
        if fmt(n.value) in reported:
            continue  # its citation is already reported as wrong
        written = text[n.start : n.end]
        problems.append(
            GateProblem(
                code="uncited_number",
                message="Not a cited official figure, and re-running the "
                "answer's tools didn't produce it.",
                number=written,
                fix="Cite the official figure it comes from, include the tool call "
                "that computed it, or remove it.",
            )
        )

    mentions = find_editions(text)
    for n in numbers:
        label = _label_after(n, mentions, numbers)
        if label is None:
            continue
        matched = [f for f in used if _same(n.value, f.c.value)]
        cited = {f.c.edition for f in matched}
        # A label is right when that edition prints this value too ("322
        # (JFF-2023 to JFF-2025)": all three print 322).
        prints_it = any(
            (r := f.row(label)) is not None and _same(r.shown, n.value) for f in matched
        )
        if cited and label not in cited and not prints_it:
            written = text[n.start : n.end]
            problems.append(
                GateProblem(
                    code="edition_label",
                    message=f"{written} is labelled {label} in the text, but its "
                    f"citation is {', '.join(sorted(cited))}.",
                    number=written,
                    fix=f"Label it {sorted(cited)[0]}, or cite {label}'s value.",
                )
            )

    problems += _consistency(used, pub_order, text_of)
    for phrase in advocacy_phrases(text):
        problems.append(
            GateProblem(
                code="advocacy",
                message=f'"{phrase}" argues for an outcome; saved answers stay '
                "neutral.",
                fix="Report the figures and the thresholds, without a recommendation.",
            )
        )
    basis = sorted(
        {f.c.edition for f in used if not f.checked.historical},
        key=lambda e: pub_order.get(e, 0),
    )
    return GateReport(
        passed=not problems,
        problems=problems,
        citations=[f.checked for f in used],
        computed=computed_hits,
        edition_basis=basis,
        numbers_checked=len(numbers),
    )
