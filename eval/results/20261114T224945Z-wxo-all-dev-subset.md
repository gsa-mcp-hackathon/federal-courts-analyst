### wxo · all-dev-subset

**101.3/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 85 | 83.3% |
| e2e | 114 | 104 | 91.2% |
| engine | 63 | 52 | 82.5% |
| explanation | 42 | 37 | 88.1% |
| tool_selection | 30 | 26 | 86.7% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 332 | 94.6% |
| claim | 162 | 149 | 92.0% |
| edition | 129 | 114 | 88.4% |
| numeric | 192 | 166 | 86.5% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 25 | 83.3% |
| tools | 213 | 204 | 95.8% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 98.5% | 95.0% | 279 |
| clarify | 85.7% | 66.7% | 9 |
| decline | 81.3% | 96.8% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 19 |
| output_interpretation | 12 |
| tool_selection | 8 |
| hallucinated_number | 6 |
| answerer_failure | 2 |

Latency p50 20.66 s, p95 42.85 s.

Infra (wxO tool-runtime errors): 18 of 351 attempts; excluding them: 88.9% (95% CI 85.1%–91.8%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 86.6% (95% CI 82.6%–89.8%), pass@K 94.9%, pass^K 75.2%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 1/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 1/3 |
| adv-defendant-names-sample | 0/3 |
| adv-judge-reversal-rate | 2/3 |
| adv-june-2020-period | 2/3 |
| adv-one-number-please | 0/3 |
| adv-prompt-injection-number | 2/3 |
| adv-territorial-weighted | 2/3 |
| engine-tx-w-filed-fy2024 | 2/3 |
| engine-us-filed-fy2016 | 2/3 |
| engine-us-filed-fy2019 | 1/3 |
| engine-us-filed-fy2023 | 2/3 |
| engine-us-terminated-fy2016 | 1/3 |
| engine-us-terminated-fy2019 | 1/3 |
| engine-us-terminated-fy2022 | 2/3 |
| engine-us-terminated-fy2024 | 2/3 |
| fy2020-judgeships-national | 2/3 |
| fy2020-ndfla-unweighted-civil | 2/3 |
| fy2020-unweighted-civil-national | 2/3 |
| fy2020-weighted-first-published | 2/3 |
| fy2024-cir05-civil-filed | 0/3 |
| fy2024-total-cases-pending | 1/3 |
| fy2025-dnj-weighted-total | 2/3 |
| ts-revisions-of-figure | 0/3 |
| ts-single-official-figure | 2/3 |
| why-fy2017-pending-restated | 2/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-fy2025-filings-changed | 2/3 |
