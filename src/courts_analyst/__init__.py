"""courts_analyst: an edition-aware MCP server for federal court statistics.

Layout (see docs/adr/0002-core-adapter-architecture.md):
  core/      pure domain logic; no MCP or HTTP imports
  pipeline/  data ingestion (official tables, IDB)
  tools/ resources/ prompts/  thin MCP adapters over core/
  api/       FastAPI adapter over core/ (REST + agent stream)
  agent/     model adapters and MCP client wiring
"""

__version__ = "0.1.0"

SERVER_NAME = "Federal Courts Analyst"
SERVICE_ID = "federal-courts-analyst"
