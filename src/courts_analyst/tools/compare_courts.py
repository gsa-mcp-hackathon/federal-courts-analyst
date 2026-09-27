"""`compare_courts`: rank courts on one published measure, from one edition."""

from __future__ import annotations

from typing import Annotated, Literal

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.enums import CourtCode, EditionSelector
from courts_analyst.core.official import CourtComparison, compare_courts
from courts_analyst.core.results import Result, clarify
from courts_analyst.tools._common import READ_ONLY, ask, core_errors, get_db
from courts_analyst.tools._vocab import AMBIGUOUS, MeasureOrAlias

DESCRIPTION = """\
Use this when the user wants courts compared or ranked on one published \
measure in one fiscal year: "the five districts with the highest weighted \
filings per judgeship in FY2024", "compare S.D.N.Y., E.D.N.Y. and D.N.J.", \
"which Fifth Circuit districts are busiest".

Not for a single court's figure (use get_official_figure) or for why a \
court's number changed (use explain_change). Weighted filings come only from \
the official tables here.

Returns ranked rows (rank, court, value), all from one edition and table, \
plus the national figure from the same edition and, when a later edition \
revised the national figure, that one too with a warning. Omit courts to \
rank all districts; a circuit code ranks its districts. order='asc' for \
lowest first (for example fastest median times).

Example: measure='weighted_total_filings_per_judgeship', fiscal_year=2024, \
top_n=5 → N.D. Fla. 4,357, E.D.N.C. 834, E.D. Cal. 790, … (JB-2024 X-1A)."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="compare_courts",
        description=DESCRIPTION,
        annotations={"title": "Compare courts", **READ_ONLY},
    )
    @core_errors
    async def compare_courts_tool(
        measure: Annotated[MeasureOrAlias, Field(description="The statistic.")],
        fiscal_year: Annotated[int, Field(ge=1990, le=2030)],
        courts: Annotated[
            list[CourtCode] | None,
            Field(
                description="Courts to compare; omit for every district. A circuit "
                "code means its districts."
            ),
        ] = None,
        top_n: Annotated[int | None, Field(ge=1, le=94)] = None,
        order: Literal["desc", "asc"] = "desc",
        edition: EditionSelector = "latest",
        ctx: Context | None = None,
    ) -> Result[CourtComparison] | mcp_types.InputRequiredResult:
        if measure in AMBIGUOUS:
            answer = await ask(ctx, AMBIGUOUS[measure])
            if isinstance(answer, mcp_types.InputRequiredResult):
                return answer
            if answer is None:
                return clarify(AMBIGUOUS[measure], CourtComparison)
            measure = answer
        expanded = _expand_circuits(courts)
        return compare_courts(
            get_db(), measure, fiscal_year, expanded, edition, top_n, order
        )


def _expand_circuits(courts: list[str] | None) -> list[str] | None:
    """A circuit code means its districts (plus the circuit row itself)."""
    if not courts:
        return None
    from courts_analyst.core.cohorts import expand_courts
    from courts_analyst.core.courts import COURTS, CourtLevel

    out: list[str] = []
    for c in courts:
        if COURTS[c].level is CourtLevel.CIRCUIT:
            out.extend(expand_courts([c]))
        else:
            out.append(c)
    return list(dict.fromkeys(out))
