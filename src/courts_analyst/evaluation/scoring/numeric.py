"""Numeric and edition checks.

A figure counts as reported when a stated number equals the expected value at
the expected value's printed precision (322 matches 322.2 and 321.6, not
321.4), or lies within the item's tolerance. It is attributed correctly only
when the edition stated next to it is the expected edition: 322 attributed to
JB-2020 is wrong even though the number is right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from courts_analyst.evaluation.records import ReportedFigure
from courts_analyst.evaluation.schema import ExpectedFigure


def printed_decimals(value: float) -> int:
    """Decimals a value was written with (``322.0`` → 0, ``20.3`` → 1)."""
    if float(value).is_integer():
        return 0
    return len(repr(float(value)).split(".", 1)[1])


def value_matches(reported: float, expected: ExpectedFigure) -> bool:
    half_unit = 0.5 * 10.0 ** -printed_decimals(expected.value)
    # A hair under half a unit so 321.5 doesn't round-trip to 322 both ways.
    allowed = max(expected.allowed_error(), half_unit - 1e-9)
    return abs(reported - expected.value) <= allowed


@dataclass
class FigureCheck:
    expected: ExpectedFigure
    value_found: bool = False
    edition_ok: bool = False
    editions_seen: list[str | None] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value_found and self.edition_ok


def check_figure(
    expected: ExpectedFigure, reported: list[ReportedFigure]
) -> FigureCheck:
    check = FigureCheck(expected)
    for r in reported:
        if value_matches(r.value, expected):
            check.value_found = True
            check.editions_seen.append(r.edition)
    if not expected.editions:
        check.edition_ok = check.value_found
    else:
        check.edition_ok = any(e in expected.editions for e in check.editions_seen)
    return check


@dataclass
class FiguresResult:
    checks: list[FigureCheck]
    mode: str

    def _agg(self, attr: str) -> bool:
        vals = [getattr(c, attr) for c in self.checks]
        return all(vals) if self.mode == "all" else any(vals)

    @property
    def numeric_ok(self) -> bool:
        return self._agg("value_found")

    @property
    def edition_ok(self) -> bool:
        return self._agg("ok")

    @property
    def needs_edition(self) -> bool:
        return any(c.expected.editions for c in self.checks)


def check_figures(
    expected: list[ExpectedFigure], mode: str, reported: list[ReportedFigure]
) -> FiguresResult:
    return FiguresResult([check_figure(e, reported) for e in expected], mode)
