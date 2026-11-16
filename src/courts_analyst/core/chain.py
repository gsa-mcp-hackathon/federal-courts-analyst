"""Edition chains: every published value of one figure, oldest edition first.

Shared by official figures, explanations, reconciliation and revision notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from courts_analyst.core.db import Database
from courts_analyst.core.numbers import fmt, round_half_up
from courts_analyst.core.provenance import FigureRef, RevisionStatus

CHAIN_SQL = """
SELECT o.edition, o.table_code, o.value, o.decimals, e.pub_order, o.cell_ref,
       s.url, o.period_end, o.footnote_ids
FROM cat.observation o
JOIN cat.edition e USING (edition)
JOIN cat.source_file s USING (file_id)
WHERE o.measure_id = ? AND o.court = ? AND o.fiscal_year = ? AND o.value IS NOT NULL
ORDER BY e.pub_order
"""


@dataclass(frozen=True)
class Row:
    """One edition's printing of a figure."""

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
        """The value as printed (rounded like the table)."""
        return round_half_up(self.value, self.decimals)

    def ref(self) -> FigureRef:
        return FigureRef(
            value=self.shown,
            edition=self.edition,
            table_code=self.table_code,
            url=self.url,
            cell_ref=self.cell_ref,
        )


def load_chain(db: Database, measure: str, court: str, fy: int) -> list[Row]:
    return [
        Row(e, t, v, d if d is not None else 0, p, c, u, pe, list(f or []))
        for e, t, v, d, p, c, u, pe, f in db.rows(CHAIN_SQL, [measure, court, fy])
    ]


def revision_status(chain: list[Row]) -> RevisionStatus:
    if len(chain) == 1:
        return "only_edition"
    return "revised" if len({r.shown for r in chain}) > 1 else "original"


def later_revisions(chain: list[Row]) -> list[FigureRef]:
    """Every edition whose printed value differs from the one before it."""
    return [cur.ref() for prev, cur in pairwise(chain) if cur.shown != prev.shown]


def history_text(chain: list[Row]) -> str:
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
