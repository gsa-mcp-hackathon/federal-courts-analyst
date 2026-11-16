"""`explain_term`: definitions of terms, measures and nature-of-suit codes."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.glossary import TermLookup, explain_term
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db

DESCRIPTION = """\
Use this when the user asks what a term, code or statistic means: "weighted \
filings", "directly filed MDL", "nature of suit 442", "statistical year", \
"what is Judicial Facts and Figures", "Table X-1A".

Not for numbers (use get_official_figure) or for why they changed \
(explain_change).

Returns the definition with its source (glossary, measure registry or the \
IDB codebook), related terms, and the measure id or nature-of-suit group when \
there is one. Unknown terms return found=false with "did you mean" \
suggestions instead of a guess.

Example: term='nature of suit 442' → Employment (civil rights), Table C-2 \
group Civil Rights."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="explain_term",
        description=DESCRIPTION,
        annotations={"title": "Explain a term", **READ_ONLY},
    )
    @core_errors
    async def explain_term_tool(
        term: Annotated[str, Field(min_length=1, max_length=120)],
    ) -> Result[TermLookup]:
        return explain_term(term, get_db())
