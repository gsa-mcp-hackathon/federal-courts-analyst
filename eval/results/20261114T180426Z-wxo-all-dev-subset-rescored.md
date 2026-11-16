### wxo · rescored:20261114T180426Z-wxo-all-dev-subset

**303/351 correct (86.3%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 81 | 79.4% |
| e2e | 114 | 107 | 93.9% |
| engine | 63 | 55 | 87.3% |
| explanation | 42 | 33 | 78.6% |
| tool_selection | 30 | 27 | 90.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 333 | 94.9% |
| claim | 162 | 141 | 87.0% |
| edition | 129 | 120 | 93.0% |
| numeric | 192 | 175 | 91.1% |
| ranking | 12 | 10 | 83.3% |
| revision | 30 | 26 | 86.7% |
| tools | 213 | 206 | 96.7% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 96.5% | 97.5% | 279 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 91.0% | 96.8% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 16 |
| output_interpretation | 15 |
| hallucinated_number | 10 |
| tool_selection | 6 |
| answerer_failure | 1 |

Latency p50 21.37 s, p95 42.53 s.

Infra (wxO tool-runtime errors): 14 of 351 attempts; excluding them: 86.6% (95% CI 82.6%–89.9%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 86.3% (95% CI 82.3%–89.5%), pass@K 92.3%, pass^K 75.2%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 0/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 2/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-one-number-please | 0/3 |
| adv-territorial-weighted | 1/3 |
| engine-ca-c-filed-fy2020 | 2/3 |
| engine-us-filed-fy2016 | 2/3 |
| engine-us-filed-fy2019 | 2/3 |
| engine-us-filed-fy2023 | 2/3 |
| engine-us-pending-fy2023 | 2/3 |
| engine-us-terminated-fy2016 | 2/3 |
| engine-us-terminated-fy2018 | 2/3 |
| engine-us-terminated-fy2019 | 2/3 |
| explain-direct-filed-mdl | 2/3 |
| fy2019-2020-civil-filed-change | 2/3 |
| fy2020-weighted-total-national | 2/3 |
| fy2024-cir05-civil-filed | 2/3 |
| fy2024-sdny-weighted-total | 2/3 |
| fy2024-top5-civil-filed | 2/3 |
| fy2024-total-cases-pending | 2/3 |
| fy2025-bottom3-weighted-total | 2/3 |
| ts-revisions-of-figure | 0/3 |
| why-fy2020-civil-filings-jump | 2/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-weighted-differs-from-raw | 0/3 |
| why-weighted-ndfla-drop-fy2025 | 2/3 |
