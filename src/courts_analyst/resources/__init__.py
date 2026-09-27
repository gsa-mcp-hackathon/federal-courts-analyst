"""Resources: documents a client can read directly by URI.

| URI | Content |
| --- | --- |
| ``courts://catalog`` | Editions, tables (years, source URLs), measures, IDB |
| ``courts://revisions`` | Every figure a later edition revised (the revision log) |
| ``courts://glossary`` | The glossary |
| ``courts://editions/{edition}/{table}`` | One published table (immutable) |
| ``courts://codebook/{field}`` | IDB code lists with validity ranges |
| ``courts://methodology/{topic}`` | Short methodology notes |

FastMCP 4 has only server-wide cache hints (ADR 0001), so immutability is
also stated in each edition resource's ``_meta``.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import yaml
from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError

from courts_analyst.core.catalog import overview, published_table, revisions
from courts_analyst.core.enums import EDITIONS
from courts_analyst.core.errors import CoreError
from courts_analyst.core.glossary import glossary
from courts_analyst.tools._common import get_db

CODEBOOK_FIELDS = (
    "arbit", "circuit", "classact", "disp", "district", "ifp", "judgment",
    "juris", "jury", "noj", "nos", "origin", "procprog", "prose", "statuscd",
    "trclact",
)  # fmt: skip
METHODOLOGY_TOPICS = (
    "weighted-filings",
    "mdl",
    "fiscal-vs-statistical-year",
    "reconciliation",
    "editions",
)
TABLES = ("X-1A", "C-1", "C-5", "6.1", "6.2", "6.3")

_BOTH = {"audience": ["user", "assistant"]}


def _json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


def _guard(fn: Any) -> Any:
    import functools

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except CoreError as err:
            raise ResourceError(err.message) from err

    return wrapper


def register_resources(mcp: FastMCP) -> None:
    """Register all resources with the MCP server."""

    @mcp.resource(
        "courts://catalog",
        name="catalog",
        title="Table catalog",
        description="Every edition and table loaded, with fiscal years covered and "
        "source URLs; the measures; the IDB release.",
        mime_type="application/json",
        annotations={**_BOTH, "priority": 0.9},
    )
    @_guard
    def catalog() -> str:
        return _json(overview(get_db()).model_dump())

    @mcp.resource(
        "courts://revisions",
        name="revisions",
        title="Revision log",
        description="Every figure whose printed value changed between editions: "
        "measure, court, fiscal year, first and latest edition and value.",
        mime_type="application/json",
        annotations={**_BOTH, "priority": 0.7},
    )
    @_guard
    def revision_log() -> str:
        return _json([r.model_dump() for r in revisions(get_db())])

    @mcp.resource(
        "courts://glossary",
        name="glossary",
        title="Glossary",
        description="Definitions of the terms the tables and this server use.",
        mime_type="application/json",
        annotations={**_BOTH, "priority": 0.6},
    )
    def glossary_resource() -> str:
        return _json(glossary())

    @mcp.resource(
        "courts://editions/{edition}/{table}",
        name="edition_table",
        title="Published table (one edition)",
        description="One table from one edition as normalised JSON: every value "
        f"with its cell reference, plus the table's notes. Editions: {EDITIONS[0]} "
        f"… {EDITIONS[-1]}; tables: {', '.join(TABLES)} (6.x are JFF, the rest "
        "JB). A published edition never changes, so this is safe to cache.",
        mime_type="application/json",
        annotations={**_BOTH, "priority": 0.5},
        meta={"immutable": True, "cache": "immutable"},
    )
    @_guard
    def edition_table(edition: str, table: str) -> str:
        return _json(published_table(get_db(), edition, table).model_dump())

    @mcp.resource(
        "courts://codebook/{field}",
        name="codebook",
        title="IDB codebook field",
        description="Codes, labels and validity dates for one IDB field "
        f"({', '.join(CODEBOOK_FIELDS)}).",
        mime_type="application/json",
        annotations={**_BOTH, "priority": 0.4},
    )
    def codebook(field: str) -> str:
        if field not in CODEBOOK_FIELDS:
            raise ResourceError(
                f"Unknown codebook field {field!r}. "
                f"Fields: {', '.join(CODEBOOK_FIELDS)}."
            )
        text = resources.files("courts_analyst.pipeline.idb").joinpath(
            f"codebook/{field}.yaml"
        )
        return _json(yaml.safe_load(text.read_text()))

    @mcp.resource(
        "courts://methodology/{topic}",
        name="methodology",
        title="Methodology note",
        description="How the server handles a topic: "
        + ", ".join(METHODOLOGY_TOPICS)
        + ".",
        mime_type="text/markdown",
        annotations={**_BOTH, "priority": 0.8},
    )
    def methodology(topic: str) -> str:
        if topic not in METHODOLOGY_TOPICS:
            raise ResourceError(
                f"Unknown topic {topic!r}. Topics: {', '.join(METHODOLOGY_TOPICS)}."
            )
        return (
            resources.files("courts_analyst.resources")
            .joinpath(f"methodology/{topic}.md")
            .read_text()
        )


__all__ = ["register_resources"]
