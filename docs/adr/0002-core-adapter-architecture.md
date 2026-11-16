# ADR 0002: One pure core, thin MCP and HTTP adapters

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The same answers have to reach three surfaces: MCP tools (Claude, watsonx,
Databricks agents), the REST API behind the web explorer, and the eval harness.
If each surface computes figures its own way, they will drift apart. For a
project whose pitch is "the right number, with its edition", that would be fatal.

## Decision

All domain logic lives in `src/courts_analyst/core/`: provenance, the measures
registry, cohorts, `explain_change`, reconciliation and guardrails. `core/`
takes and returns plain Python and Pydantic values and **must not import**
`fastmcp`, `mcp`, `starlette`, `fastapi` or `httpx`.

Adapters are thin:

| Adapter | Location | Job |
| --- | --- | --- |
| MCP tools/resources/prompts | `tools/`, `resources/`, `prompts/` | Validate input, call core, return a model; MCP-specific concerns such as elicitation and annotations |
| REST + agent SSE | `api/` | HTTP routing, streaming, serving the web build |
| Agent | `agent/` | Model adapters; talks to our server *through MCP* like any client |
| Pipelines | `pipeline/` | Offline ingestion that writes DuckDB; core only reads it |

Shared Pydantic models (provenance, enums) live in `models.py` so core and the
adapters use the same types.

## Consequences

- Core is unit-tested without an MCP client or HTTP server.
- The explorer and the MCP tools can't disagree, because they run the same code.
- `tests/test_architecture.py` fails CI if `core/` imports an adapter library.
- mypy runs in strict mode on `core/` and `models.py`.
- There is a little duplication at the edges (an MCP tool and a REST endpoint
  may both wrap the same core function). We accept that.
