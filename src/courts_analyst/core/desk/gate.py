"""The verification gate: an answer is saved only if every number in it is
backed by the official data, and its figures come from consistent editions.

Rules (ADR 0013, decision 5):

1. Every cited value is exactly what that edition printed.
2. Every number in the text is a cited value, a published threshold (430,
   600), or the difference between two cited values of one measure. Fiscal
   years and table codes are not numbers here. A number the text attributes
   to an edition ("322 (JFF-2024)") must be cited from that edition.
3. The cited figures of each measure come from one consistent set of
   editions (``guardrails.vintage``: one publication series, and no edition
   used for one figure printing another one differently). A figure quoted as
   an earlier edition's value, in a sentence that says so ("first published
   as 554"), is history, not part of the set.
4. The text argues for no outcome.

A refusal names each number and what to write instead.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from courts_analyst.core.chain import Row, load_chain
from courts_analyst.core.db import Database
from courts_analyst.core.desk.models import (
    CheckedCitation,
    CitationIn,
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


def verify(db: Database, text: str, citations: Iterable[CitationIn]) -> GateReport:
    """Check an answer and its citations; nothing is written here."""
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
    numbers = [n for n in figures_in_text(text) if not _is_year(n, text)]
    allowed = thresholds()

    used: list[_Figure] = []
    text_of: dict[int, str] = {}
    for f in figures:
        hits = [n for n in numbers if _same(n.value, f.c.value)]
        if not hits:
            continue  # cited but not quoted: not saved
        used.append(f)
        text_of[id(f)] = text[hits[0].start : hits[0].end]
        f.checked.historical = not _same(f.c.value, f.checked.latest_value) and all(
            REVISION_WORDS.search(text[n.sentence[0] : n.sentence[1]]) for n in hits
        )

    differences = {
        round(abs(a.c.value - b.c.value), 6)
        for a in used
        for b in used
        if a is not b and a.c.measure == b.c.measure
    }
    for n in numbers:
        if any(_same(n.value, f.c.value) for f in used):
            continue
        if any(_same(n.value, t) for t in allowed):
            continue
        if round(n.value, 6) in differences:
            continue
        if fmt(n.value) in reported:
            continue  # its citation is already reported as wrong
        written = text[n.start : n.end]
        problems.append(
            GateProblem(
                code="uncited_number",
                message=f"{written} isn't backed by a cited official figure.",
                number=written,
                fix="Cite the official figure it comes from, or remove it.",
            )
        )

    mentions = find_editions(text)
    for n in numbers:
        label = _label_after(n, mentions, numbers)
        if label is None:
            continue
        cited = {f.c.edition for f in used if _same(n.value, f.c.value)}
        if cited and label not in cited:
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
        edition_basis=basis,
        numbers_checked=len(numbers),
    )
