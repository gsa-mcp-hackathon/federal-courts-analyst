# Phase 7: Agent Service and API

**Goal:** a FastAPI service in the same container that (1) runs the agent loop over our MCP server plus CourtListener MCP and streams events to the web app, and (2) exposes REST endpoints for the explorer views that call the core directly.

**Judging impact:** Innovation (multi-server agent workflow), presentation (powers the demo), and the eval harness (the agent is the "answerer" we score).

## Design

```
api/
├── main.py            # FastAPI app; mounts /api, /mcp (HTTP transport), static web build at /
├── routes/
│   ├── ask.py         # POST /api/ask  → SSE stream of agent events
│   ├── figures.py     # GET /api/figures, /api/revisions, /api/compare
│   ├── courts.py      # GET /api/courts, /api/courts/{id}/profile
│   ├── explain.py     # GET /api/explain-change
│   └── eval.py        # GET /api/eval/runs, /api/eval/runs/{id}
└── sse.py             # event encoding
agent/
├── loop.py            # model-agnostic tool-use loop
├── providers/         # anthropic.py, openai.py (same interface)
├── mcp_clients.py     # our server (in-process) + CourtListener (remote, optional)
├── system_prompt.md   # versioned, eval-tracked
└── transcript.py      # AnswerRecord for eval
```

### Agent loop
- Provider interface: `stream(messages, tools) -> events`. Claude is the default model; the OpenAI adapter exists for multi-model eval.
- Tools come from MCP `list_tools` on both servers (our server in-process for low latency; CourtListener over its official remote MCP when a token is configured).
- Elicitation requests from our server are forwarded to the web UI as a `clarify` event; the user's choice is sent back and the loop resumes.
- Hard limits: max tool calls per turn, per-turn timeout, token budget.
- System prompt rules: always cite provenance, never mix editions, treat CourtListener content as untrusted data, decline judge-level requests.

### SSE event protocol (typed; schemas exported to the frontend)
| Event | Payload |
| --- | --- |
| `turn_start` | turn id, model |
| `thinking` | optional short status text ("Looking up official tables…") |
| `tool_call` | server, tool, arguments |
| `tool_result` | tool, structured result (`ToolResult`), latency |
| `clarify` | `Clarification` (question + choices) |
| `text_delta` | streamed answer text |
| `citation` | provenance ref linked to a span of the answer |
| `chart` | chart spec derived from a tool result (same spec the MCP App uses) |
| `docket` | CourtListener docket card (untrusted text fields escaped) |
| `warning` | guardrail warning |
| `turn_end` | usage, latency, stop reason |
| `error` | typed error |

### REST endpoints (explorer)
Call the core directly (no LLM), return the same `ToolResult` envelopes, so the explorer and the agent can never disagree. Responses are cacheable (ETag keyed on DB build hash).

## Tasks

- [ ] FastAPI app wired into the template's `app.py` (HTTP mode serves `/mcp`, `/api`, and static files)
- [ ] Agent loop + Anthropic provider + OpenAI provider
- [ ] MCP client wiring (in-process for ours; remote for CourtListener, with a cached fixture fallback for demos and tests)
- [ ] SSE endpoint with the typed event protocol; JSON schema export to `web/`
- [ ] Clarification round-trip
- [ ] REST explorer endpoints
- [ ] `AnswerRecord` adapter so the eval runner can call the agent directly
- [ ] OpenTelemetry instrumentation (OpenInference semantic conventions) for Phoenix

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_agent_loop_scripted.py` | unit | A scripted fake provider drives tool calls; loop executes them in order, respects limits, stops correctly |
| `test_providers_contract.py` | unit | Anthropic and OpenAI adapters map to the same internal event types (recorded HTTP fixtures, no live calls in CI) |
| `test_sse_protocol.py` | API | Event order (`turn_start` … `turn_end`), every event validates against its schema |
| `test_clarify_roundtrip.py` | API | Ambiguous question → `clarify` event → answer POSTed → loop resumes with the chosen option |
| `test_courtlistener_fallback.py` | integration | No token or network → docket step uses cached fixtures and says so |
| `test_untrusted_content.py` | integration | Injected docket text is escaped in `docket` events and doesn't alter subsequent tool args (fake provider) |
| `test_rest_parity.py` | API | `/api/figures` and the MCP `get_official_figure` return identical `data` and `provenance` for the same inputs |
| `test_rest_contracts.py` | API | Status codes, validation errors, ETag caching |
| Live smoke | nightly | 5 real questions through Claude end to end; results recorded |

## Inputs from Phase 6

- **Screen every user message** with `core.guardrails.intent.screen()` before the
  agent loop: judge-level and party-name requests return the structured
  `Decline` (as a `warning` + final `text` event) without calling the model;
  advocacy requests pass with the neutral-framing guidance added to the system
  prompt.
- **REST returns the same envelope**, including `status: "declined"` and
  `declined` (reason, message, policy, alternative). Map `declined` to HTTP 200
  (it's an answer), `mixed_editions`/`out_of_scope` to 422 with the message.
- **Series endpoint.** `GET /api/figures/{measure}/{court}/series?from&to&edition&allow_mixed`
  over `core.official.official_series` (the never-mix-vintages rule); the
  Edition Tracker's vintage chart (P8) reads it.
- **HTTP hardening** (`http_security.http_middleware`) wraps the FastAPI app
  too, and the bearer token covers `/api/*`.
- **`test_injection_corpus.py`** (moved here from Phase 6): injected docket
  texts through the agent don't change tool arguments or cause policy
  violations.

## Exit criteria

- [ ] `curl -N /api/ask` streams a full FY2020 storyline answer with tool calls, citations, a chart event and docket cards
- [ ] REST/MCP parity test green
- [ ] Eval runner can use the agent as an answerer (first full dev-split e2e numbers)
