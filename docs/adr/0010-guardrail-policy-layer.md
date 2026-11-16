# ADR 0010: Guardrails as one policy layer in the core, failing closed

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

Phase 6 adds the conclusions the server won't draw: statistics on too few
cases, judge-level analysis, party names, silent mixing of editions,
improvised facts about periods the catalog doesn't hold, and advocacy.
Before this phase the rules were scattered (small-cell checks in the cohort
code, revision warnings in official figures) and not enforced anywhere as a
whole: the `count` metric, for example, returned a value while marking it
suppressed, and a cohort of three cases reported "Only 3 cases match".

MCP tools and the Phase 7 REST API must behave identically, and MCP tools
never see the user's words, only structured arguments.

## Decision

1. **One layer, in the core.** `core/guardrails/` holds one module per policy
   (`small_cells`, `vintage`, `periods`, `intent`, `pii`) and settings in
   `core/data/guardrails.yaml`. Every core function that returns a `Result` is
   decorated with `@guarded`, which runs `apply_policies(result, context)` and
   registers the function. A test walks the core and fails if any
   `Result`-returning function isn't registered, and another checks every tool
   calls only guarded functions.
2. **Declines are results, not errors.** `Result.status` gains `declined`
   with a `Decline` (reason, message, the policy and its source, an
   alternative). A policy `DeclinedError` inside a guarded function becomes
   that result. Clients get a structured, schema-valid answer they can relay.
3. **Invariants fail closed.** `apply_policies` checks every result: no
   suppressed cell carries a number, no statistic rests on fewer than 10
   cases, inferred explanations carry `inferred_not_official`, revised figures
   carry `revised_figure`, JB and JFF values of one measure never combine
   without `mixed_editions`, the server's own summary sentences never argue for
   an outcome, and the result fits the output budget. A broken invariant is a
   bug: the result raises `PolicyViolationError` and never leaves the server.
4. **Small cells protect against subtraction.** Counts of 1–9 are
   suppressed; when a breakdown's total is shown, the smallest visible cells
   are withheld too until no withheld cell can be pinned to one value under a
   stated attacker model (property-tested against a brute-force attacker).
   `explain_change` folds small rows into "All other" instead, so its
   breakdowns still add up exactly.
5. **Never mix vintages.** A set of official points is consistent when it
   comes from one publication series and no edition used for one point prints
   another point differently (pending counts' routine prior-year restatement
   excepted in one direction). `official_series` and `explain_change` pick a
   consistent set or refuse with `mixed_editions` unless mixing is explicitly
   requested, and then every point names its edition.
6. **PII: structure first, scanner second.** Party names stay out of the
   database (ADR 0007). Every result is also scanned against a hashed index of
   multi-word party names built by the IDB pipeline; a match withholds the
   whole result. The server's own vocabulary is allowed, and court names act
   as phrase boundaries, which took false positives on 867 real results from
   12 to 0. If the IDB is loaded but the index isn't, IDB-derived results are
   withheld.
7. **Free text is screened where it exists.** A pattern classifier
   (`intent.screen`) flags judge-level and party-name requests, and advocacy
   (answered neutrally, not declined). It runs on `explain_term` today and on
   the agent and REST inputs in Phase 7. Over MCP the judge policy is also
   structural: no tool input can name a judge (test-enforced).

## Consequences

- Output schemas change: counts can be `null` when suppressed, results carry
  `declined`, official figures carry `citation`. The frontend schemas were
  regenerated.
- Some national-level breakdowns show fewer rows (small rows fold into "All
  other"); totals are unchanged.
- The PII index (about 9 MB for the full release) ships in `data/build` next
  to `idb.duckdb`. It holds keyed hashes, not names; anyone with the public IDB
  could confirm a guessed name, which the public IDB already allows.
- The request classifier is patterns, not a model: cheap and auditable, but it
  can be phrased around. The structural guarantees (no judge data, no party
  names) don't depend on it.
