# ADR 0001: FastMCP 4 and the MCP capabilities matrix

- **Status:** Accepted
- **Date:** 2026-09-26
- **Evidence:** Phase 0 spike (throwaway scripts, not committed) plus the tests
  in `tests/test_registration.py`, `tests/test_transport.py` and
  `tests/test_docker.py`, which now guard each "yes" below.

## Context

The GSA template declared `fastmcp>=2.0.0` and its `uv.lock` resolved to
**FastMCP 3.4.7** (MCP SDK 1.29). The current release is **FastMCP 4.0.10**
(MCP SDK 2.2.0), which implements MCP spec **2026-07-28**. That spec revision
is a large change:

- **Stateless protocol:** no `initialize` handshake and no `Mcp-Session-Id`.
  Each request carries its protocol version and client capabilities in `_meta`.
  Servers must implement `server/discover`.
- **Multi round-trip requests (MRTR):** server-initiated requests
  (`elicitation/create`, `sampling/createMessage`, `roots/list`) are replaced.
  A tool returns `InputRequiredResult` and the client retries the call with
  `inputResponses`.
- **Cache hints:** list and read results carry `ttlMs` and `cacheScope`.
- `ping` and `logging/setLevel` are removed. Roots, Sampling and Logging are
  deprecated. Tasks moved to an extension.
- Servers should return `tools/list` in a deterministic order.

Clients will be a mix of eras during the hackathon: Claude Desktop/Code, MCP
Inspector, watsonx Orchestrate and Databricks agents may still speak 2025-11-25.

## Decision

**Upgrade to FastMCP 4 (`fastmcp>=4.0.10,<5`).** FastMCP 4 negotiates both the
2026-07-28 era and every handshake-era version back to 2024-11-05, so moving
costs us no older clients. Staying on 3.x would leave us on the previous spec
for the whole competition, even though the judges look for current MCP design.

Python: the floor stays at **3.11** so the template's deploy hosts keep working.
We develop and ship the container on **3.12**, and CI tests both.

## Capabilities matrix

Tested with FastMCP 4.0.10 and MCP SDK 2.2.0 on 2026-09-26. "Modern" means a
2026-07-28 client; "legacy" means a 2025-11-25 handshake client
(`Client(mode="legacy")`).

| Feature we plan to use | Modern | Legacy | Notes / how we use it | Phase |
| --- | --- | --- | --- | --- |
| Pydantic tool inputs with validation errors | Yes | Yes | Bad input → `ToolError` with the field errors | P5 |
| `outputSchema` generated from a Pydantic return type | Yes | Yes | Every tool returns a model; test enforces a schema on each tool | P0 ✓ |
| `structuredContent` + typed `.data` on the client | Yes | Yes | `server_info` already does this | P0 ✓ |
| Tool annotations (`readOnlyHint`, etc.) | Yes | Yes | All our tools are read-only | P0 ✓ |
| Deterministic `tools/list` order | Yes | Yes | Test asserts a stable order | P0 ✓ |
| Resources, templated resources, resource `annotations` (audience, priority) | Yes | Yes | `courts://catalog`, `courts://table/{id}` | P5 |
| Cache hints (`ttlMs`/`cacheScope`) | Yes | n/a | Only server-wide: `FastMCP(cache_ttl=…, cache_scope=…)`, no per-resource TTL | P5 |
| Prompts | Yes | Yes | | P5 |
| Elicitation via MRTR (`InputRequiredResult`, `ctx.input_responses`) | Yes | **No** | On a legacy connection the call fails ("MRTR only exists at 2026-07-28") | P5 |
| Elicitation via `ctx.elicit()` (server-initiated) | **No** | Yes | Raises on modern connections | P5 |
| Elicitation when the client has no handler | **No** | **No** | Fails with "Elicitation not supported" | P5 |
| MCP Apps: `ui://` resource (`text/html;profile=mcp-app`) + tool `_meta.ui.resourceUri` | Yes | Yes | `@mcp.resource("ui://…", app=True)` and `@mcp.tool(app={…})`; rendering depends on the host | P9 |
| In-memory `Client` for tests | Yes | Yes | Both eras are covered by fixtures in `tests/conftest.py` | P0 ✓ |
| stdio transport | Yes | Yes | Real subprocess test in `test_transport.py` | P0 ✓ |
| Streamable HTTP transport + custom `/health`, `/version` routes | Yes | Yes | Tested in-process, as a subprocess, and in the Docker image | P0 ✓ |
| Sampling, roots, server logging to client | Deprecated | — | **Not used.** The agent calls model APIs directly (P7) and we log to stderr/JSON | — |
| Background tasks | Extension | — | Not needed (queries take well under a second); needs `fastmcp[tasks]` | — |

## Fallback plans

1. **Elicitation (the risky one).** A single helper in the tools layer will
   choose the path per request:
   - modern client with elicitation capability → return `InputRequiredResult` (MRTR);
   - legacy client with elicitation capability → `ctx.elicit(...)`;
   - no elicitation capability → **don't ask**. Return a normal structured result
     with `status: "needs_clarification"`, the candidate choices (for example
     the available editions) and the default we would pick. The agent or user
     then calls again with an explicit argument.
   Every elicitation-driven tool must also accept the answer as an ordinary
   argument, so elicitation stays a convenience rather than a requirement. Tests
   cover all three paths.
2. **Per-resource cache TTLs:** not available, so we set one conservative
   server-wide TTL (the data only changes when we rebuild) and put edition dates
   in resource content.
3. **MCP Apps rendering:** hosts that don't render `ui://` still get the
   tool's `structuredContent` and a text summary. The chart is never the only
   way to see an answer.
4. **FastMCP 4 regression during the event:** pin the exact patch version in
   `uv.lock` (CI installs with `--frozen`). Going back to 3.x is a one-line
   change today because nothing yet depends on 4-only APIs. After P5 (MRTR)
   it would mean dropping to the fallback path in (1).

## Things to know when coding against FastMCP 4

- It uses `httpx2` internally. We don't depend on it; our own HTTP code (P1)
  uses `httpx`.
- SDK v2 renamed camelCase attributes: use `tool.output_schema`,
  `template.uri_template` and `resource.mime_type` (the old names still work
  but warn).
- `ctx.sample()` and `ctx.list_roots()` are gone. `mount(prefix=…)` became
  `mount(namespace=…)`.
- Pydantic ≥ 2.12 and Starlette ≥ 1.0.1 are required, so FastAPI must be
  ≥ 0.133 (P7).

## Still to verify (needs a person at the keyboard)

- Claude Desktop connecting over stdio (Claude Code is verified; see the Phase 0
  Evidence section).
- Verified: Claude Code (stdio), MCP Inspector v2.8.0 web UI (stdio,
  negotiated 2025-11-25) and CLI (HTTP). See the Phase 0 Evidence section.

## Sources

- MCP spec 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- FastMCP 3 → 4 upgrade guide: https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3
- FastMCP elicitation (MRTR guard pattern): https://gofastmcp.com/servers/elicitation
- PyPI: https://pypi.org/project/fastmcp/ (4.0.10), https://pypi.org/project/mcp/ (2.2.0)
