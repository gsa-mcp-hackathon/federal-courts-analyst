# ADR 0011: One HTTP app; an agent over our own MCP server; narrow CourtListener wrappers

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

Phase 7 adds a REST API for the web explorer and an agent that answers
questions in the web app, streamed to the browser. Both must agree with the
MCP tools figure for figure (ADR 0002, ADR 0010), run in the one container
that Databricks Apps deploys (ADR 0005), and keep the Phase 6 guarantees:
the same hardening on every route, no judge or party data, CourtListener
text treated as untrusted.

## Decision

1. **One ASGI app.** FastMCP's Starlette app is the outer app: MCP at
   `/mcp`, its lifespan (session manager) and Host/Origin guard, and our
   hardening middleware (`http_security`) wrap everything. A FastAPI app is
   mounted inside at `/api`; the web build (Phase 8) at `/`. `app.main`
   serves it with uvicorn instead of `mcp.run`.
2. **REST calls the core directly** and returns the same `Result` envelope
   the tools return; a parity test compares them field by field.
   `declined` and `needs_clarification` are 200 (they're answers); core
   error codes map to fixed statuses (422 for bad or out-of-scope input,
   404 for not published, 503 when data isn't built). Responses carry an
   ETag keyed on the data build and the URL.
3. **The agent talks to our server through MCP, in process** (FastMCP's
   in-memory client): the model gets exactly the tools, descriptions,
   guardrails and elicitation any MCP client gets, with no network hop.
   A thin provider interface (`stream(system, messages, tools)` → text
   deltas, tool uses, done) has Anthropic (default, Claude Sonnet 5) and
   OpenAI adapters and a scripted one for tests and offline demos.
4. **The loop owns the policy the server can't see.** Every question goes
   through `intent.screen()` first; judge and party requests are declined
   without a model call. Hard limits per turn (tool calls, model requests,
   tokens, time) and a shared dollar budget in eval runs. After the model
   finishes, the loop emits a `citation` event per official figure used and
   appends the server's citation line for a revised figure quoted without
   its revision (issue #27): the model can't be relied on to keep it.
5. **Typed SSE protocol.** One discriminated union of event models
   (`agent/events.py`), exported as JSON Schema for the frontend. Every
   stream is `turn_start` … exactly one `turn_end`.
6. **Clarification keeps the stream open.** A tool's elicitation becomes a
   `clarify` event; the turn waits (up to 5 minutes) for
   `POST /api/ask/{turn_id}/clarify`, then continues in the same stream. No
   answer, or an unknown choice, counts as declined and the tool returns its
   choices to the model instead.
7. **CourtListener through two wrappers, never its raw tools.**
   `courtlistener_search_dockets` (its `search`, `type='d'` only) and
   `courtlistener_get_docket` (`get_endpoint_item` on `dockets` only), with
   our own argument schema re-checked on every call and a fixed list of
   fields requested (no case names, parties, attorneys or judges). Results
   are reduced to those fields, cleaned (control and bidi characters
   removed, HTML-escaped, capped) and labelled untrusted. Without a token,
   or when CourtListener fails, a committed fixture of synthetic dockets
   answers, and says so.
8. **Tracing through the OpenTelemetry API** with OpenInference attributes
   (AGENT, LLM, TOOL spans) for Phoenix; no exporter unless
   `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and user text only as a hash
   unless `AGENT_TRACE_CONTENT=true`.

## Consequences

- One port, one deploy, one set of middleware: nothing reaches `/api`
  without the same headers, CORS, size limit, rate limit and bearer token as
  `/mcp`.
- The agent can never disagree with the tools, and eval runs of the agent
  measure the same server Claude Desktop sees. The agent is also an eval
  answerer (`--answerer agent`).
- Pending clarifications live in process memory: run one worker, or sticky
  sessions, until a shared store is needed.
- Case names from CourtListener are withheld by design; if the domain
  expert decides public captions are acceptable, it's one field in
  `SAFE_FIELDS`.
- The strict API CSP (`default-src 'none'`) doesn't suit HTML pages, so the
  Swagger page is off (`/api/openapi.json` remains) and the web build will
  need its own CSP in Phase 8.

## Alternatives considered

- **Mount the MCP app inside FastAPI.** Works, but the hardening middleware
  and the MCP lifespan would have to be re-attached by hand, and a missed
  route would be unprotected.
- **Call the core directly from the agent.** Faster to write, but the agent
  would drift from what MCP clients see, and elicitation would need a
  second implementation.
- **Give the model CourtListener's MCP tools directly.** It exposes judge
  search, party and attorney endpoints, and write tools (alerts); an
  allowlist by tool name alone still leaves judge search (`type='p'`) and
  arbitrary `fields`.
- **Resume a clarification with a new request** (stateless). Needs the whole
  conversation serialized to the client or a store; keeping the stream open
  is simpler for one worker, and the protocol doesn't change if we switch.
