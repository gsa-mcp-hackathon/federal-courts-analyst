# Reconciliation: IDB vs official tables

`reconcile` rebuilds civil cases filed, terminated and pending from IDB
records and compares them with the latest edition of Table C-1.

| Status | Meaning |
| --- | --- |
| matched | within tolerance (terminations 0.05%, filings 0.5%, pending 1%) |
| explained_variance | a quantified cause covers the gap: a restated figure the IDB matches, repeat records, undated reopenings, or snapshot drift |
| unexplained | none does |

Across FY2016–FY2025, every national figure matches and every termination
count matches exactly. The FY2017 pending count first published as 339,131
was restated to 366,195 in the next edition; the IDB reconstruction (363,601)
matches the restated figure. See docs/variance-report.md in the repository.
