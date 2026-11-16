"""`server_info`: identity, protocol support and data readiness.

A cheap, dependency-free tool so smoke tests and clients always have
something to call, and so an agent can check whether data is loaded before
asking a statistics question.
"""

from __future__ import annotations

from fastmcp import FastMCP
from mcp_types.version import SUPPORTED_PROTOCOL_VERSIONS

from courts_analyst import SERVER_NAME, __version__
from courts_analyst.config import settings
from courts_analyst.models import DataStatus, ServerInfo

COVERAGE = (
    "Built by `make data`: (1) six uscourts.gov district court tables (X-1A, "
    "C-1, C-5 from Judicial Business; 6.1, 6.2, 6.3 from Judicial Facts and "
    "Figures) in every edition covering FY2016–FY2025, with revisions tracked "
    "across editions; (2) the FJC Integrated Database civil file: every case "
    "active in FY2015–FY2025, one row per record, all codes decoded, party names "
    "excluded. Tools: official figures and revisions, court comparisons, change "
    "explanations, IDB cohorts, reconciliation, judgeship context, definitions "
    "and example dockets."
)


def register(mcp: FastMCP) -> None:
    """Register the `server_info` tool."""

    @mcp.tool(
        name="server_info",
        annotations={
            "title": "Server info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def server_info() -> ServerInfo:
        """Report this server's version, supported MCP protocol versions, whether
        its court-statistics database has been built, and which tools it offers.

        Call this first if you are unsure whether data is loaded. It takes no
        arguments, makes no network calls and never changes anything.
        """
        tools = await mcp.list_tools()
        datasets: dict[str, DataStatus] = {
            name: "ready" if path.is_file() else "not_built"
            for name, path in (
                ("official_tables", settings.resolved_duckdb_path),
                ("idb_civil", settings.resolved_idb_path),
            )
        }
        return ServerInfo(
            name=SERVER_NAME,
            version=__version__,
            protocol_versions=sorted(SUPPORTED_PROTOCOL_VERSIONS, reverse=True),
            data_status=datasets["official_tables"],
            datasets=datasets,
            coverage=COVERAGE,
            tools=sorted(t.name for t in tools),
        )
