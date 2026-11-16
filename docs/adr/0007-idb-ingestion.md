# ADR 0007: Civil IDB: pinned release, record grain, party names outside the database

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The FJC civil IDB is one 2 GB tab-delimited file (330 MB zipped) that the FJC
replaces in place every quarter. Profiling the August 2026 release showed:

1. **It isn't clean text.** A few Latin-1 and control bytes, and 638 rows
   where a quoted party name contains a tab and shifts every later column.
2. **Repeat records aren't snapshots.** The plan assumed duplicates were
   release snapshots to collapse to the latest. They are cases terminated,
   reopened and terminated again, and every termination is counted in the
   official tables: counting each terminated record reproduces Table C-1
   terminations exactly for FY2016–FY2025. Collapsing them would lose about
   22,000 FY2017 terminations.
3. **Party names are the only PII**, and nothing the server does needs them.

## Decision

- **Pin the release, fail on change.** `data/manifest/idb.yaml` records the
  sha256, size, Last-Modified and ETag. A different release fails the fetch
  (`ReleaseChangedError`) unless `--accept-new-release` re-pins it. Downloads
  resume with `Range` + `If-Range`, so a mid-download release change restarts
  instead of splicing two releases.
- **Normalize in a streaming pass** (Latin-1 decode, control bytes to spaces,
  quote-aware re-split of rows with the wrong field count, fail with the line
  number otherwise), then let DuckDB read the clean text with an exact column
  list. The header must match a known schema exactly.
- **Record grain with two views.** `idb_civil_record` has one row per record,
  sequenced per case over the whole release. `idb_civil` (latest record per
  case) is for filings and cohorts; `idb_civil_terminations` (every terminated
  record) is for terminations.
- **Separate database file.** The IDB goes to `data/build/idb.duckdb`, not
  `courts.duckdb`, so the two pipelines rebuild independently (10 s vs 80 s)
  and the server attaches both read-only in Phase 4.
- **Party names outside the database.** They go to
  `data/private/idb_parties.parquet`, which is never mounted into the server,
  and are dropped from every table. Judge columns must be blank or the build
  fails.
- **Codebook as reviewed YAML**, one file per field, with each nature-of-suit
  code placed in the Table C-2 hierarchy and checked against C-2's FY2024
  column.
- **Commit a sample in the FJC's own format** (150 KB, synthetic names), so CI
  exercises the same normalize → load path as the full build.

Alternatives considered: the per-year SAS datasets (needs a SAS reader and
pandas; same records); `ignore_errors` in DuckDB's CSV reader (drops the 638
shifted rows silently); keeping party names in a table the tools don't query
(one bad query away from a leak); one row per case only (loses terminations).

## Consequences

- A new FJC release is an explicit decision: re-run with
  `--accept-new-release`, review the profile diff, and commit the new pins.
  Exact counts in the docs then change slightly; the `@fulldata` tests compare
  with official tables and ranges, not fixed counts.
- Pending counts for past dates have to be reconstructed because reopening
  dates aren't recorded; FY2017 is 7% above C-1 (S.D. W. Va. MDL). Phase 4
  reconciliation owns that explanation.
- Phase 4 must choose the right view per measure (cases for filings, records
  for terminations). The methodology doc spells this out.
