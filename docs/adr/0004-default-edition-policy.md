# ADR 0004: Latest edition by default, first-published attached

- **Status:** Proposed. Confirm with the domain expert before Phase 1 (plan
  README, "Proposed decisions" #1).
- **Date:** 2026-09-26

## Context

For recent years the judiciary publishes more than one official figure for the
same statistic. A table first published in one edition is revised in later
editions (the concept document's example: 554 first published, 322 in a later
edition). A user asking "how many…?" usually wants the current official number.
A journalist or oversight user checking an old report needs the number as it was
first published. A tool that silently returns one of them is wrong half the time.

## Decision

1. When no edition is given, return the figure from the **latest** edition that
   covers the requested period.
2. Every figure carries a provenance block: table ID, edition (publication
   date), source URL and retrieval date.
3. When the first-published value differs from the returned value, the response
   also includes **`first_published`** (value and edition) and the **revision
   history**, so the difference is always visible and never has to be discovered.
4. Callers can ask for `edition="first_published"`, `edition="latest"` or a
   specific edition date.
5. Tools never average or merge figures from different editions.

## Consequences

- The 554 vs 322 story appears whenever it applies, without the user having to
  know to ask.
- Answers can change when a new edition is published. That's correct behavior,
  and the provenance date explains it.
- Golden-figure tests (P1) must pin both the latest and the first-published
  value for each revised statistic.
- If the domain expert prefers first-published as the default, only step 1
  changes. The data model and responses stay the same.
