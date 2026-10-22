# Architecture decision records

Short records of decisions that shape the codebase. Add one when a choice is
hard to reverse or would surprise a new reader. Format: context, decision,
consequences. Status is one of Proposed, Accepted, Superseded.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-mcp-capabilities.md) | FastMCP 4 and the MCP capabilities matrix | Accepted |
| [0002](0002-core-adapter-architecture.md) | One pure core, thin MCP and HTTP adapters | Accepted |
| [0003](0003-duckdb-analytical-store.md) | DuckDB as the analytical store | Accepted |
| [0004](0004-default-edition-policy.md) | Latest edition by default, first-published attached | Proposed (implemented in P4; awaiting domain expert) |
| [0005](0005-frontend-served-from-python.md) | Frontend served from the Python container | Accepted |
| [0006](0006-official-tables-ingestion.md) | Official tables: committed manifest, label-based parsing, PDF cross-check | Accepted |
| [0007](0007-idb-ingestion.md) | Civil IDB: pinned release, record grain, party names outside the database | Accepted |
| [0008](0008-analytics-core.md) | Analytics core: one read-only connection, result envelopes, labelled inference | Accepted |
| [0009](0009-mcp-tool-surface.md) | MCP tool surface: flat typed arguments, one envelope, elicitation as a convenience | Accepted |
| [0010](0010-guardrail-policy-layer.md) | Guardrails as one policy layer in the core, failing closed | Accepted |
| [0011](0011-agent-and-api.md) | One HTTP app; an agent over our own MCP server; narrow CourtListener wrappers | Accepted |
| [0012](0012-web-app.md) | Web app: typed from the backend schemas, charts from validated tokens, a derived district map | Accepted |
| [0013](0013-request-desk.md) | A sandboxed request desk; the official data stays read-only | Proposed (implemented in P9b; awaiting team, GSA, domain expert) |
