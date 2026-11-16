# ADR 0009: MCP tool surface: flat typed arguments, one envelope, elicitation as a convenience

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Phase 5 exposes the analytics core (ADR 0008) as MCP tools. The rubric names
MCP design principles: Pydantic inputs, precise descriptions, goal-oriented
tools. Clients differ: 2026-07-28 clients (MRTR elicitation), 2025-11-25
clients (`ctx.elicit()`), and clients with no elicitation at all (headless
agents, watsonx, Databricks).

## Decision

1. **Nine goal-oriented tools plus `server_info`**, one file each, registered
   in a fixed order (flagship first) so `tools/list` is stable.
2. **Flat, typed arguments.** Each tool takes named parameters with
   `Annotated[...]` constraints rather than one nested input model; the core's
   Pydantic models validate them (`CohortSpec`, closed vocabularies). A nested
   `{"input": {...}}` object is harder for models to fill. Courts, measures,
   editions and codebook values are JSON Schema `enum`s.
3. **The core's `Result[T]` is the output schema.** Tools return it
   unchanged, so `outputSchema`, `structuredContent`, REST (P7) and the
   frontend schemas are one contract. `Result` is parametrised per data type
   so serialisation never warns.
4. **Descriptions follow one template**, linted by a test: *Use this when…*
   (what question), *Not for…* (the neighbouring tool), *Returns…*, *Example:*.
   ≤ 1,200 characters. They carry the reporting rules the model must relay
   (name the edition, flag revisions, label inference, report n).
5. **Elicitation is a convenience, never a requirement.** Ambiguous measure
   aliases (`filings_per_judgeship`, `civil_filings`) are the only triggers.
   One helper picks the path per request: modern client with elicitation →
   `InputRequiredResult` (MRTR) and the answer read from `ctx.input_responses`
   on the retry; legacy client with elicitation → `ctx.elicit()`; no
   capability, or the user declines → a normal result with
   `status: needs_clarification` and the same choices. Every choice is also an
   ordinary argument. Soft ambiguities (edition, statistical year) never ask:
   the default applies and a warning says so.
6. **Errors are typed and actionable**: a core error becomes
   `ToolError("[code] message Next: …")`; invalid arguments are rejected by
   the schema before the tool runs.
7. **Read-only annotations** on every tool (`readOnlyHint`, not destructive,
   idempotent); `openWorldHint` only on `sample_dockets`, whose links point to
   CourtListener.
8. **Revisions travel with the figure.** `get_official_figure` carries
   `revision_notes` (the official history, plus the gated inference from ADR
   0008) so the reason two editions differ is in the same result.
9. **Logging** records tool name, an argument hash (never the arguments),
   latency, result size and status. One server-wide cache TTL (an hour); edition
   resources also carry `_meta.immutable` (ADR 0001: no per-resource TTL).

## Consequences

- Tool-selection accuracy on the dev split is 100% with Claude Sonnet (target
  ≥ 90%); every tool works on 2026-07-28 and 2025-11-25 clients, over stdio,
  HTTP and in the container.
- Headless agents never see an elicitation; they get the choices as data and
  either pick one or ask the user.
- Cohort handles are per process in HTTP mode unless `COHORT_STORE_PATH` is
  set; because they're deterministic, a replica that doesn't know a handle
  asks the agent to call `find_cases` again.
