# Architecture decision records

Short records of decisions that shape the codebase. Add one when a choice is
hard to reverse or would surprise a new reader. Format: context, decision,
consequences. Status is one of Proposed, Accepted, Superseded.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-mcp-capabilities.md) | FastMCP 4 and the MCP capabilities matrix | Accepted |
| [0002](0002-core-adapter-architecture.md) | One pure core, thin MCP and HTTP adapters | Accepted |
| [0003](0003-duckdb-analytical-store.md) | DuckDB as the analytical store | Accepted |
| [0004](0004-default-edition-policy.md) | Latest edition by default, first-published attached | Proposed (awaiting domain expert; P1 data supports either default) |
| [0005](0005-frontend-served-from-python.md) | Frontend served from the Python container | Accepted |
| [0006](0006-official-tables-ingestion.md) | Official tables: committed manifest, label-based parsing, PDF cross-check | Accepted |
| [0007](0007-idb-ingestion.md) | Civil IDB: pinned release, record grain, party names outside the database | Accepted |
