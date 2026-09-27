"""Find the figures an answer reports and the edition each is attributed to.

Structured citations (:attr:`AnswerRecord.cited_figures`) come first. Prose is
the fallback: every number is paired with the nearest edition mention within
a short window, preferring one that follows it ("322 (JFF-2023)") over one
before it. Editions are recognised as ids (``JFF-2023``, ``JB 2020``) or
titles ("Judicial Business 2020", "the 2023 Judicial Facts and Figures").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure

WINDOW = 90
"""Characters between a number and an edition mention that still pair them."""

_SERIES_TITLES = {
    "JB": r"judicial\s+business(?:\s+of\s+the\s+united\s+states\s+courts)?",
    "JFF": r"judicial\s+facts\s+(?:and|&)\s+figures",
    "FCMS": r"federal\s+court\s+management\s+statistics",
}

_EDITION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("id", re.compile(r"\b(JB|JFF|FCMS|STFJ|FJCS)[-\s](\d{4})\b", re.I)),
    *[
        (
            code,
            re.compile(
                rf"\b{title}\s*(?:\(|,)?\s*(?:table\s+[\w.-]+\s*,?\s*)?(\d{{4}})\b",
                re.I,
            ),
        )
        for code, title in _SERIES_TITLES.items()
    ],
    *[
        (
            code,
            re.compile(rf"\b(\d{{4}})\s+(?:edition\s+of\s+(?:the\s+)?)?{title}", re.I),
        )
        for code, title in _SERIES_TITLES.items()
    ],
]

# Numbers not glued to letters or hyphens (skips FY2020, JB-2020, X-1A, 6.2 in
# "Table 6.2"); thousands separators allowed.
_NUMBER = re.compile(
    r"(?<![\w.\-/])(-?\d{1,3}(?:,\d{3})+|-?\d+)(\.\d+)?(?![\w\-/]|\.\d)"
)
_TABLE_BEFORE = re.compile(r"(?:table|tables|mdl|no\.|number|§)\s*$", re.I)


@dataclass(frozen=True)
class _Mention:
    edition: str
    start: int
    end: int


def find_editions(text: str) -> list[_Mention]:
    """Every edition mention in ``text``, normalised to ids like ``JB-2020``."""
    out: list[_Mention] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in _EDITION_PATTERNS:
        for m in pattern.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            if kind == "id":
                edition = f"{m.group(1).upper()}-{m.group(2)}"
            else:
                edition = f"{kind}-{m.group(1)}"
            out.append(_Mention(edition, m.start(), m.end()))
            taken.append((m.start(), m.end()))
    return sorted(out, key=lambda x: x.start)


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z*(\[])|\n+")
# "N.D. Fla., M.D. Ga." and "Tex. Table" aren't sentence ends: a short
# capitalised word or initials before the period is an abbreviation.
_ABBREV = re.compile(r"(?:\b[A-Z][a-z]{0,3}|(?:\b[A-Z]\.)+[A-Z]?|\bNo|\bv|\bvs)\.$")


def _sentence_bounds(text: str) -> list[tuple[int, int]]:
    bounds, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        if not m.group().startswith("\n") and _ABBREV.search(text[: m.start()]):
            continue
        bounds.append((start, m.start()))
        start = m.end()
    bounds.append((start, len(text)))
    return bounds


def _nearest_edition(
    start: int, end: int, mentions: list[_Mention], sentence: tuple[int, int]
) -> str | None:
    """Nearest edition in the same sentence; otherwise within WINDOW chars."""
    lo, hi = sentence
    same = [m for m in mentions if m.start >= lo and m.end <= hi]
    if same:
        after = [m for m in same if m.start >= end]
        before = [m for m in same if m.end <= start]
        if after:
            return min(after, key=lambda m: m.start - end).edition
        if before:
            return max(before, key=lambda m: m.end).edition
    best: tuple[float, str] | None = None
    for m in mentions:
        if m.start >= end:
            dist = float(m.start - end)
        elif m.end <= start:
            dist = (start - m.end) * 1.5  # prefer an edition that follows
        else:
            continue
        if dist <= WINDOW and (best is None or dist < best[0]):
            best = (dist, m.edition)
    return best[1] if best else None


def figures_in_text(text: str) -> list[ReportedFigure]:
    """Numbers in prose, each with its nearest edition (or None)."""
    mentions = find_editions(text)
    spans = [(m.start, m.end) for m in mentions]
    sentences = _sentence_bounds(text)
    out: list[ReportedFigure] = []
    for m in _NUMBER.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue  # the year inside "JB-2020"
        if _TABLE_BEFORE.search(text[max(0, m.start() - 12) : m.start()]):
            continue
        raw = m.group(1).replace(",", "") + (m.group(2) or "")
        out.append(
            ReportedFigure(
                value=float(raw),
                edition=_nearest_edition(
                    m.start(),
                    m.end(),
                    mentions,
                    next(b for b in sentences if b[0] <= m.start() <= b[1]),
                ),
            )
        )
    return out


def reported_figures(record: AnswerRecord) -> list[ReportedFigure]:
    """Declared citations plus figures found in the final text."""
    return [*record.cited_figures, *figures_in_text(record.final_text)]
