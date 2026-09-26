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
from courts_analyst.models import ServerInfo

COVERAGE = (
    "Planned: uscourts.gov statistical tables across published editions "
    "(FY2015–FY2025) and the FJC civil Integrated Database FY2015–FY2025. "
    "No statistics tools are available yet."
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
        return ServerInfo(
            name=SERVER_NAME,
            version=__version__,
            protocol_versions=sorted(SUPPORTED_PROTOCOL_VERSIONS, reverse=True),
            data_status=(
                "ready" if settings.resolved_duckdb_path.is_file() else "not_built"
            ),
            coverage=COVERAGE,
            tools=sorted(t.name for t in tools),
        )
