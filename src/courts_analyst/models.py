"""Shared Pydantic models for tool inputs and outputs.

Tools return these models so FastMCP publishes a precise `outputSchema` and
clients receive `structuredContent`. Provenance and edition models land here
in Phase 1/4.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DataStatus = Literal["not_built", "ready"]


class ServerInfo(BaseModel):
    """Identity and readiness of the Federal Courts Analyst server."""

    name: str = Field(description="Human-readable server name.")
    version: str = Field(description="Server package version (semver).")
    protocol_versions: list[str] = Field(
        description="MCP protocol versions this server can negotiate, newest first."
    )
    data_status: DataStatus = Field(
        description=(
            "'ready' when the official tables catalog exists; 'not_built' before "
            "`make data` has run, in which case data tools will be unavailable. "
            "See `datasets` for each dataset."
        )
    )
    datasets: dict[str, DataStatus] = Field(
        description=(
            "Readiness of each dataset: 'official_tables' (uscourts.gov tables "
            "with edition history, courts.duckdb) and 'idb_civil' (FJC Integrated "
            "Database civil records, idb.duckdb)."
        )
    )
    coverage: str = Field(
        description="Plain-language summary of what the data covers.",
    )
    tools: list[str] = Field(description="Names of the tools this server exposes.")
