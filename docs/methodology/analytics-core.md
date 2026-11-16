# Methodology: the analytics core

How the server turns the two datasets into answers (Phase 4). Code:
[`src/courts_analyst/core/`](../../src/courts_analyst/core/). Design decisions:
[ADR 0008](../adr/0008-analytics-core.md).

## Official figures

`get_official_figure(measure, court, fiscal_year, edition)` returns one value
as printed in one edition, plus every edition that printed it:

- **Default edition: latest** (ADR 0004). `first_published` and every later
  revision are always attached, and a revised figure carries a
  `revised_figure` warning with its history, for example
  *554 (JB-2020 to JFF-2022) → 322 (JFF-2023 to JFF-2025)*.
- `edition` may be `latest`, `first_published` or an edition id; an edition
  that doesn't print the figure is an error that lists the ones that do.
- **Revision status:** `only_edition` (printed once), `original` (reprinted
  unchanged) or `revised` (a later edition printed a different value at the
  table's precision).
- **Statistical years:** JFF's 1990 rows cover the 12 months ending
  June 30, 1990. They are returned with `period_type: statistical_year` and a
  `period_mismatch` warning.
- **Not published** is distinguished from **out of scope**: weighted filings
  for the territorial courts (excluded from the case-weight studies) or
  national-only tables (6.1–6.3) for a district are `not_published`; a year
  outside the catalog is `out_of_scope` with the available years.

`compare_courts` ranks courts on one measure from **one** edition. District
values exist only in the first-published Judicial Business edition, so when
the national figure was revised later (FY2024: 502 in JB-2024, 453 in
JFF-2024), both national values are returned and the warning says to compare
districts with the same-edition national figure.

## Cohorts

A cohort is a `CohortSpec` (courts, fiscal years, basis, nature of suit,
origin, jurisdiction, disposition, pro se, class action, MDL docket). Its
handle is `coh_` + the first 12 hex digits of SHA-256 over the normalised
spec, so the same filters give the same handle everywhere.

- **Grain:** filings cohorts read `idb_civil` (one row per case), termination
  cohorts `idb_civil_terminations` (every terminated record), as in Phase 2.
- **Metrics:** count, trend by fiscal year, median days to disposition,
  disposition rates, judgment-for rates, share by nature-of-suit group, pro se
  share, share still pending. Each result has `n`.
- **Intervals:** Wilson 95% intervals for shares; for medians the
  distribution-free interval between two order statistics (exact binomial
  ranks for n ≤ 200, normal approximation above). A simulation test checks its
  coverage.
- **Small cells** (plan decision 3, reviewed in Phase 6): fewer than 30 cases
  → `small_cell` caution; fewer than 10 → the value is withheld
  (`suppressed`, severity `block`).
- **Data breaks** in the window are attached when they bear on the filters:
  a new nature-of-suit code only for cohorts using that code or its group,
  origin 13 only for MDL cohorts, the pandemic window always.
- Recent cohorts are still open, so medians and outcome rates cover only
  terminated cases; the result says so.

## explain_change

**Counts** (filed, terminated, pending). The official change comes from Table
C-1 (latest edition of each year). The IDB rebuilds both years and splits the
change by district, by nature-of-suit group and by the pair; each list sums
exactly to the IDB change. For filings, the change **excluding directly filed
MDL cases** is also reported (FY2019 → FY2020: +173,239 with them, −6,502
without). A gap between the IDB and official change of more than 2% is flagged.

**Per judgeship.** With F filings and J judgeships, the change in F/J splits
exactly into

    filings effect   = (F₂ − F₁) · (1/J₁ + 1/J₂) / 2
    judgeship effect = (F₁ + F₂) / 2 · (1/J₂ − 1/J₁)

The filings effect is split by district from Table X-1A (district value ×
district judgeships), in the first-published series, the only one with
district rows; an "unallocated" row absorbs rounding in the published values.

**Drivers**, each labelled with what backs it:

| Driver | Basis | Fires when |
| --- | --- | --- |
| `mdl_direct_filed` / `mdl_cases` | IDB-derived | MDL filings (or MDL terminations / pending) changed by ≥ 1,000 or ≥ 25% of the change; lists the top MDL dockets |
| `pandemic_window` | context | the window includes FY2020 or FY2021 |
| `methodology_revision` | official | an endpoint's figure was revised between editions (with its history) |
| `methodology_revision` | **inferred** | national per-judgeship revision where one district's filings cover ≥ 50% of the revision *and* most of its filings that year were directly filed MDL cases |
| `judgeship_change` | official | authorized judgeships changed enough to move the figure by ≥ 0.5 |
| `data_break` | context | a codebook change in the window touches a key contributor's case type |

The flagship result: FY2020 weighted civil filings per judgeship were 554 in
JB-2020; N.D. Fla.'s filings contribute **211 points** of it, and the later
editions' figure is **232 points** lower. That is consistent with the revised
series excluding or down-weighting those cases, but no published note says
so, so the driver is `inferred` and the result carries an
`inferred_not_official` warning until the AO confirms (issue #8).

## Reconciliation

`reconcile` rebuilds civil cases filed, terminated and pending for a court
(district, circuit or nation) and fiscal year and compares them with the
**latest** edition of Table C-1:

| Status | Rule |
| --- | --- |
| matched | within tolerance: terminations 0.05% (min 2 cases), filings 0.5% (min 10), pending 1% (min 25) |
| explained variance | a quantified cause covers the gap: *restated* (another edition printed a value the IDB matches), *repeat records* (filings short by no more than the court-year's repeat records), *undated reopenings* (pending short by no more than records terminated before and after the date), or *snapshot drift* (within 0.5% / 2% / 3% for records corrected since publication) |
| unexplained | anything else |

The tolerances were fixed before running the report. Results for
FY2016–FY2025 are in the generated [variance report](../variance-report.md):
every national figure matches, and **all 1,060 termination court-years match**.
A cohort handle can be reconciled only when it corresponds to a published
count (courts, one fiscal year, a basis, no other filters).

**Issue #11 resolved:** the FY2017 national pending count first published in
JB-2017 (339,131) was restated in JB-2018 (366,195). The IDB reconstruction
(363,601) is within 0.71% of the restated figure; S.D. W. Va. (71,478 vs
71,454) is within 0.03%.

## Judgeship context

`judgeship_context(court, fiscal_year)` reports the court's weighted total
filings per judgeship from Table X-1A (the first-published edition, the only
one with district rows), weighted civil filings and authorized judgeships
from the same edition, the national figure from that edition, and:

- the Judicial Conference's **430** standard for considering an additional
  judgeship and the **600** judicial-emergency threshold, each with its
  source ([CRS Insight IN12541](https://www.congress.gov/crs-product/IN12541),
  [AO judicial emergency definition](https://www.uscourts.gov/judicial-emergency-definition));
- the Conference's **2025 recommendation** for the court, if any
  ([Table 1](https://www.uscourts.gov/sites/default/files/2025-03/2025_judicial_conference_recommendations.pdf),
  69 district judgeships in 25 districts; sha256-pinned in
  `core/data/judgeships.yaml`).

It never recommends anything and doesn't claim a judicial emergency, which
depends on vacancies the server doesn't track.

## Glossary

`explain_term` searches the reviewed glossary (`core/data/glossary.yaml`, 29
entries with sources), the measures registry and the IDB codebook's
nature-of-suit codes ("nature of suit 442", "NOS 830", "442"). Unknown terms
get "did you mean" suggestions, never a guess.
