"""Never mix vintages: every multi-year set of official figures comes from one
consistent series, or says plainly that it doesn't.

Editions revise figures (FY2020 weighted civil filings per judgeship: 554 in
JB-2020, 322 from JFF-2023), and the two publication series differ in method
(FY2024: 384 in JB-2024, 335 in JFF-2024). Taking "the latest value" for each
year separately can therefore splice series together. A set of points is
**consistent** when

1. all of them come from one publication series (Judicial Business or
   Judicial Facts and Figures), and
2. no edition used for one point prints a *different* value for another
   point in the set (the set doesn't contradict its own sources).

Pending counts are the exception to (2) in one direction: each Judicial
Business edition restates the prior year's closing pending count (Table
C-1), routinely. For those measures an older edition's first printing of the
next year doesn't count against the restated value; a newer edition that
disagrees with an older value still does.

:func:`choose_vintage` picks a consistent set for a selector, and refuses
(:class:`~courts_analyst.core.errors.MixedEditionsError`) when none exists,
unless the caller passes ``allow_mixed=True``; then every point carries its
edition and the result a ``mixed_editions`` caution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from courts_analyst.core.chain import Row
from courts_analyst.core.enums import EDITIONS
from courts_analyst.core.errors import (
    MixedEditionsError,
    OutOfScopeError,
    UnknownEditionError,
)
from courts_analyst.core.numbers import fmt
from courts_analyst.core.results import Caveat

Chains = Mapping[int, list[Row]]


def series_of(edition: str) -> str:
    """``JB`` or ``JFF``."""
    return edition.split("-", 1)[0]


def routinely_restated(measure: str) -> bool:
    """Measures each edition restates for the prior year (pending counts)."""
    return measure.endswith("_pending")


def contradictions(
    chosen: Mapping[int, Row], chains: Chains, restated: bool = False
) -> list[str]:
    """Where an edition used for one point prints another point differently.

    With ``restated``, only a *newer* edition disagreeing counts."""
    out = []
    for fy, row in chosen.items():
        for other_fy, other in chosen.items():
            if other_fy == fy or other.edition == row.edition:
                continue
            if restated and row.pub_order < other.pub_order:
                continue
            same = next((r for r in chains[other_fy] if r.edition == row.edition), None)
            if same is not None and same.shown != other.shown:
                out.append(
                    f"{row.edition} (used for FY{fy}) prints FY{other_fy} as "
                    f"{fmt(same.shown)}, not the {fmt(other.shown)} from "
                    f"{other.edition}"
                )
    return out


def is_consistent(
    chosen: Mapping[int, Row], chains: Chains, restated: bool = False
) -> bool:
    if len({series_of(r.edition) for r in chosen.values()}) > 1:
        return False
    return not contradictions(chosen, chains, restated)


@dataclass(frozen=True)
class Vintage:
    """The points chosen for each year and how they were chosen."""

    points: dict[int, Row]
    label: str
    consistent: bool
    warnings: tuple[Caveat, ...] = ()


def _single_edition(chains: Chains, latest: bool = True) -> dict[int, Row] | None:
    """Every year from the one edition (latest or earliest) printing them all."""
    shared = set.intersection(*({r.edition for r in ch} for ch in chains.values()))
    if not shared:
        return None
    order = {r.edition: r.pub_order for ch in chains.values() for r in ch}
    pick = (max if latest else min)(shared, key=order.__getitem__)
    return {fy: next(r for r in ch if r.edition == pick) for fy, ch in chains.items()}


def _mixed_text(points: Mapping[int, Row]) -> str:
    return "; ".join(
        f"FY{fy} {fmt(r.shown)} ({r.edition})" for fy, r in sorted(points.items())
    )


def choose_vintage(
    chains: Chains,
    selector: str | None = "latest",
    allow_mixed: bool = False,
    measure: str = "",
) -> Vintage:
    """One consistent row per fiscal year of ``chains`` for ``selector``.

    ``latest`` (default): each year's latest value if those are consistent;
    else the latest single edition printing every year; else each year as
    first published if that is consistent. ``first_published``: each year's
    first value, else the earliest single edition printing every year. An
    edition id: every year from that edition.
    """
    if not chains or any(not ch for ch in chains.values()):
        missing = sorted(fy for fy, ch in chains.items() if not ch)
        raise OutOfScopeError(
            "No edition prints " + ", ".join(f"FY{fy}" for fy in missing) + ".",
            ["get_official_figure to see which years are available"],
        )
    selector = selector or "latest"
    restated = routinely_restated(measure)

    def consistent(points: Mapping[int, Row]) -> bool:
        return is_consistent(points, chains, restated)

    latest = {fy: ch[-1] for fy, ch in chains.items()}
    first = {fy: ch[0] for fy, ch in chains.items()}
    if selector not in ("latest", "first_published"):
        if selector not in EDITIONS:
            raise UnknownEditionError(f"Unknown edition {selector!r}.")
        pts = {fy: r for fy, ch in chains.items() for r in ch if r.edition == selector}
        if len(pts) < len(chains):
            missing = sorted(set(chains) - set(pts))
            raise UnknownEditionError(
                f"{selector} doesn't print "
                + ", ".join(f"FY{fy}" for fy in missing)
                + ".",
                ["edition='latest' for one consistent series"],
            )
        return Vintage(pts, f"all from {selector}", True)

    primary = latest if selector == "latest" else first
    if consistent(primary):
        label = (
            "each year's latest edition (one consistent series)"
            if selector == "latest"
            else "each year as first published"
        )
        return Vintage(primary, label, True)
    single = _single_edition(chains, latest=selector == "latest")
    if single is not None and consistent(single):
        edition = next(iter(single.values())).edition
        notes = [
            f"FY{fy} {fmt(single[fy].shown)} in {edition}; {fmt(r.shown)} in "
            f"{r.edition}"
            for fy, r in sorted(primary.items())
            if r.edition != edition and r.shown != single[fy].shown
        ]
        warn = (
            (
                Caveat(
                    code="revised_figure",
                    message=f"All years are taken from {edition}, the "
                    f"{'latest' if selector == 'latest' else 'earliest'} edition "
                    "printing every one of them, so they come from one table. "
                    "Other editions print different values: " + "; ".join(notes) + ".",
                ),
            )
            if notes
            else ()
        )
        return Vintage(single, f"all from {edition}", True, warn)
    if selector == "latest" and consistent(first):
        return Vintage(
            first,
            "each year as first published",
            True,
            (
                Caveat(
                    code="revised_figure",
                    message="The latest values for these years come from different "
                    f"editions ({_mixed_text(latest)}), which don't form one "
                    "series, so each year is given as first published.",
                ),
            ),
        )
    if not allow_mixed:
        raise MixedEditionsError(
            "These years aren't printed in one consistent series: "
            + _mixed_text(primary)
            + ". Combining them would mix editions ("
            + "; ".join(
                contradictions(primary, chains, restated)[:2] or ["different series"]
            )
            + ").",
            [
                "narrow the range of years",
                "edition='first_published' or a specific edition",
                "allow_mixed=True to get every point labelled with its edition",
            ],
        )
    return Vintage(
        primary,
        "mixed editions (explicitly requested)",
        False,
        (
            Caveat(
                code="mixed_editions",
                message="These points come from different editions that don't form "
                f"one series: {_mixed_text(primary)}. Don't compute changes or "
                "ratios across them without saying so.",
            ),
        ),
    )
