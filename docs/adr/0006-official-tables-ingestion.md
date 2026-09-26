# ADR 0006: Official tables: committed manifest, label-based parsing, PDF cross-check

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The official caseload tables are small xlsx and PDF files spread across
uscourts.gov. Three facts shaped the pipeline:

1. **URLs aren't predictable.** The same table sits under `data_tables/`,
   `2025-01/` or `document/` depending on the edition. The site rate-limits
   bursts by blocking the IP for 15–20 minutes.
2. **Layouts drift.** Columns are reordered (X-1A 2016 vs 2025), groups change
   width (C-1 before and after 2023), and header wording changes ("During
   Trial" vs "Trial"), sometimes with typos ("Sept. 31, 2016").
3. **Our pitch is exact numbers with their edition.** A silently dropped or
   shifted column would be worse than a failed build.

## Decision

- **Committed manifest.** Discovery crawls the per-table listing and landing
  pages once and writes `data/manifest/tables.yaml` with every file's URL and
  sha256. Builds read only the manifest and the local cache, so they're
  offline and reproducible, and a changed published file is an error
  (`EditionChangedError`), not a silent update.
- **Parse by label.** Each table family maps printed header paths to measure
  ids with rules. Missing or duplicated measures raise `HeaderDriftError`.
- **xlsx first, PDF checked.** The catalog uses the workbook when one exists
  (exact values and display formats) and the PDF otherwise (JB-2016). Every
  PDF is parsed too, and every value both formats print must agree after
  Excel-style rounding.
- **Commit the fixtures.** All xlsx editions, the PDF-only editions and a few
  PDFs of other layouts (about 2 MB of public-domain government files) are
  committed under `tests/fixtures/tables/`. CI builds the complete catalog
  from them, so golden figures and revision tests run on every PR.

Alternatives considered: hand-written URL patterns (break on the 2024 and 2025
editions), position-based parsers per edition (brittle, and they fail
silently), PDF-only parsing (loses precision), and downloading in CI
(violates the plan's test-data rule and trips the rate limit).

## Consequences

- A new edition means re-running `make data-discover` and `make data-tables`
  and reviewing the manifest diff; a new layout shows up as a failed build
  that names the unmapped headers.
- The repo carries about 2 MB of fixtures. They're byte-identical to the
  pinned manifest (a test checks this).
- Two PDF layouts needed a family-level hint (`group_fit="centered"` for C-5)
  and an optional word in rules ("Court Action" in 6.3). Those are recorded
  next to the rules.
