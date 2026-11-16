# ADR 0008: Analytics core: one read-only connection, result envelopes, labelled inference

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Phase 4 builds the domain layer every adapter calls (MCP tools in P5, REST in
P7). It has to answer from two stores (the tables catalog and the IDB), make
every number traceable, never mix editions, and keep our own reasoning (why
554 became 322) visibly apart from what the tables say.

## Decision

1. **One in-memory DuckDB connection** attaches `courts.duckdb` as `cat` and
   `idb.duckdb` as `idb`, both `READ_ONLY`, then sets
   `enable_external_access = false`. After that no query can write, read a
   file by path, `ATTACH` or `COPY`. Every query runs on its own cursor with
   `?` parameters; SQL text is constant or built from constant fragments,
   enforced by an AST test (`tests/test_sql_safety.py`). The IDB is optional:
   without it, official figures still work and IDB features raise
   `DataUnavailableError`.
2. **Every entry point returns a `Result`** envelope: `status`
   (`ok` / `needs_clarification`), `data`, `provenance` (required: `ok()`
   refuses an empty list), `warnings` and `suggested_next`. Adapters pass it
   through unchanged, so the MCP `outputSchema`, the REST contract and the
   frontend schemas (`make schemas`) are the same model.
3. **Default edition = latest, first-published always attached** (ADR 0004,
   now implemented). A comparison across courts uses **one** edition, chosen
   as the latest that prints the most requested courts; if the national figure
   was revised later, both are shown with a warning, never swapped in.
4. **Closed vocabularies as enum schemas.** Courts, measures, editions and
   cohort fields are `str`s constrained to sets drawn from the registries and
   the codebook, published as JSON Schema `enum`s so a model can't invent
   `SDNY` or `JB2020`.
5. **Deterministic cohort handles**: `coh_` + 12 hex of SHA-256 over the
   normalised spec (sorted lists, circuits and `US` expanded to districts).
   The store is an in-process LRU with optional DuckDB persistence; a lost
   handle is recreated by calling `find_cases` again with the same filters.
6. **Exact decompositions.** Count breakdowns sum exactly to the IDB change
   (an "All other" row absorbs the tail). Per-judgeship changes use a
   symmetric shift-share whose filings and judgeship effects sum exactly to
   the change; the filings effect is split by district from the
   first-published X-1A series, the only one with district rows.
7. **Four evidence labels** on drivers: `official`, `idb_derived`, `inferred`,
   `context`. The inference that the 554 → 322 revision concerns N.D. Fla.'s
   directly filed MDL cases is emitted only when one district's filings cover
   at least half of the revision **and** most of that district's filings that
   year were directly filed MDL cases, and it always carries an
   `inferred_not_official` warning.
8. **Reconciliation compares with the latest edition** and classifies with
   tolerances set per measure before the variance report was run (terminations
   0.05%, filings 0.5%, pending 1%), then quantified causes (restated figure,
   repeat records, undated reopenings, snapshot drift within an allowance).
9. **Medians get an order-statistic CI**, not a bootstrap: exact coverage,
   reproducible, and two quantile lookups instead of thousands of resamples.
10. **Reference data lives in reviewed YAML** (`core/data/`): measures (moved
    from the pipeline so both use one file), glossary, judgeship thresholds
    and the Judicial Conference's 2025 recommendations, each with its source
    URL (the recommendations PDF is also sha256-pinned).

## Consequences

- A new tool is a thin adapter: validate, call one core function, return the
  `Result`. Nothing in `core/` imports FastMCP, FastAPI or a model SDK.
- The server can't be turned into a way to read arbitrary files or write to
  the stores, even by a query-building bug.
- Pending counts reconcile against the AO's own restatements, which resolves
  the FY2017 "+7.2%" puzzle (issue #11): JB-2018 restated FY2017 to 366,195
  and the IDB lands within 0.71% of it.
- Judicial emergency status is **not** computed: it needs vacancy data we
  don't hold. `judgeship_context` reports thresholds and the Conference's own
  recommendations only.
