### wxo · all-dev-subset

**101.7/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 81 | 79.4% |
| e2e | 114 | 107 | 93.9% |
| engine | 63 | 55 | 87.3% |
| explanation | 42 | 35 | 83.3% |
| tool_selection | 30 | 27 | 90.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 332 | 94.6% |
| claim | 162 | 145 | 89.5% |
| edition | 129 | 116 | 89.9% |
| numeric | 192 | 171 | 89.1% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 27 | 90.0% |
| tools | 213 | 202 | 94.8% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 97.1% | 97.1% | 279 |
| clarify | 25.0% | 11.1% | 9 |
| decline | 88.2% | 95.2% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 15 |
| output_interpretation | 12 |
| tool_selection | 10 |
| hallucinated_number | 7 |
| answerer_failure | 2 |

Latency p50 21.05 s, p95 47.47 s.

Infra (wxO tool-runtime errors): 19 of 351 attempts; excluding them: 87.7% (95% CI 83.7%–90.8%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 86.9% (95% CI 83.0%–90.0%), pass@K 93.2%, pass^K 77.8%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 0/3 |
| adv-arizona-how-many-cases | 1/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 2/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-judge-breakdown-ddel | 2/3 |
| adv-one-number-please | 0/3 |
| adv-out-of-scope-fy2012 | 2/3 |
| adv-territorial-weighted | 2/3 |
| engine-ny-s-filed-fy2025 | 2/3 |
| engine-tx-w-filed-fy2024 | 2/3 |
| engine-us-filed-fy2016 | 2/3 |
| engine-us-filed-fy2019 | 2/3 |
| engine-us-pending-fy2021 | 2/3 |
| engine-us-terminated-fy2016 | 1/3 |
| engine-us-terminated-fy2024 | 2/3 |
| explain-direct-filed-mdl | 2/3 |
| fy2019-2020-civil-filed-change | 2/3 |
| fy2020-ndfla-weighted-civil | 2/3 |
| fy2024-cir05-civil-filed | 0/3 |
| fy2024-total-cases-pending | 1/3 |
| ts-revisions-of-figure | 0/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-judgeships-673-vs-674 | 2/3 |
| why-weighted-differs-from-raw | 1/3 |
