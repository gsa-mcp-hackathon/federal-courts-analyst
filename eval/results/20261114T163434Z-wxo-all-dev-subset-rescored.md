### wxo · rescored:20261114T163434Z-wxo-all-dev-subset

**301/351 correct (85.8%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 78 | 76.5% |
| e2e | 114 | 109 | 95.6% |
| engine | 63 | 52 | 82.5% |
| explanation | 42 | 35 | 83.3% |
| tool_selection | 30 | 27 | 90.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 328 | 93.4% |
| claim | 162 | 145 | 89.5% |
| edition | 129 | 122 | 94.6% |
| numeric | 192 | 174 | 90.6% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 26 | 86.7% |
| tools | 213 | 208 | 97.7% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 94.5% | 98.2% | 279 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 90.0% | 85.7% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 21 |
| output_interpretation | 12 |
| hallucinated_number | 10 |
| tool_selection | 5 |
| answerer_failure | 2 |

Latency p50 21.65 s, p95 45.07 s.

Infra (wxO tool-runtime errors): 13 of 351 attempts; excluding them: 86.4% (95% CI 82.3%–89.6%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 85.8% (95% CI 81.7%–89.0%), pass@K 91.5%, pass^K 79.5%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 2/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 1/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-one-number-please | 0/3 |
| adv-sdtex-talking-points | 0/3 |
| adv-senator-letter-arizona | 0/3 |
| adv-territorial-weighted | 0/3 |
| engine-ny-s-filed-fy2025 | 2/3 |
| engine-tx-w-filed-fy2024 | 2/3 |
| engine-us-filed-fy2016 | 1/3 |
| engine-us-filed-fy2024 | 2/3 |
| engine-us-filed-fy2025 | 2/3 |
| engine-us-terminated-fy2019 | 0/3 |
| engine-us-terminated-fy2020 | 2/3 |
| engine-us-terminated-fy2025 | 2/3 |
| explain-direct-filed-mdl | 1/3 |
| fy2024-cir05-civil-filed | 1/3 |
| fy2024-total-cases-pending | 1/3 |
| fy2024-total-filings-per-judgeship | 2/3 |
| ts-revisions-of-figure | 0/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-weighted-differs-from-raw | 1/3 |
