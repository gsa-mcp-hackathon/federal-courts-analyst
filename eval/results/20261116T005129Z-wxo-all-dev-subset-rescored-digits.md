### wxo · rescored:20261116T005129Z-wxo-all-dev-subset

**310/351 correct (88.3%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 81 | 79.4% |
| e2e | 114 | 107 | 93.9% |
| engine | 63 | 62 | 98.4% |
| explanation | 42 | 35 | 83.3% |
| tool_selection | 30 | 25 | 83.3% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 332 | 94.6% |
| claim | 162 | 149 | 92.0% |
| edition | 129 | 118 | 91.5% |
| numeric | 192 | 180 | 93.8% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 27 | 90.0% |
| tools | 213 | 207 | 97.2% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 97.1% | 97.1% | 279 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 85.9% | 96.8% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 17 |
| output_interpretation | 17 |
| tool_selection | 6 |
| hallucinated_number | 1 |

Latency p50 20.36 s, p95 37.01 s.

Infra (wxO tool-runtime errors): 11 of 351 attempts; excluding them: 89.4% (95% CI 85.7%–92.3%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 88.3% (95% CI 84.5%–91.3%), pass@K 93.2%, pass^K 80.3%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 0/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 2/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-march-2021-period | 2/3 |
| adv-one-number-please | 0/3 |
| adv-territorial-weighted | 2/3 |
| engine-ca-c-filed-fy2020 | 2/3 |
| fy2017-sdwva-weighted-civil | 2/3 |
| fy2024-cir05-civil-filed | 2/3 |
| fy2024-dnj-civil-filed | 2/3 |
| fy2024-edky-judgeships | 2/3 |
| fy2024-total-cases-pending | 1/3 |
| fy2025-dnj-weighted-total | 2/3 |
| ts-explain-change-district | 1/3 |
| ts-revisions-of-figure | 0/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-fy2024-terminations-jump | 2/3 |
| why-pending-rose-fy2020-fy2021 | 2/3 |
| why-weighted-differs-from-raw | 2/3 |
| why-weighted-ndfla-drop-fy2025 | 2/3 |
