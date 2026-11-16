### wxo · rescored:20261115T025353Z-wxo-all-test2-subset

**108/135 correct (80.0%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 60 | 42 | 70.0% |
| e2e | 42 | 42 | 100.0% |
| explanation | 18 | 10 | 55.6% |
| tool_selection | 15 | 14 | 93.3% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 135 | 113 | 83.7% |
| claim | 72 | 61 | 84.7% |
| edition | 42 | 42 | 100.0% |
| numeric | 42 | 42 | 100.0% |
| ranking | 3 | 3 | 100.0% |
| tools | 81 | 80 | 98.8% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 84.3% | 92.6% | 81 |
| clarify | 100.0% | 8.3% | 12 |
| decline | 82.2% | 88.1% | 42 |

| Error category | Count |
| --- | ---: |
| task_understanding | 22 |
| output_interpretation | 4 |
| answerer_failure | 1 |

Latency p50 20.55 s, p95 34.88 s.

Infra (wxO tool-runtime errors): 9 of 135 attempts; excluding them: 80.2% (95% CI 72.3%–86.2%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 80.0% (95% CI 72.5%–85.9%), pass@K 86.7%, pass^K 73.3%

| Item | Correct attempts |
| --- | ---: |
| t2-adv-average-fy2023-weighted-civil | 1/3 |
| t2-adv-blend-fy2019-weighted-total | 0/3 |
| t2-adv-busiest-fy2019 | 0/3 |
| t2-adv-control-flm-recommendation | 1/3 |
| t2-adv-national-caseload-fy2022 | 0/3 |
| t2-adv-nj-judges-busy-fy2024 | 0/3 |
| t2-adv-sdny-how-many-fy2023 | 1/3 |
| t2-explain-median-time | 0/3 |
| t2-explain-termination | 0/3 |
| t2-ts-judgeship-context-az-fy2025 | 2/3 |
| t2-why-fy2024-filings-fell | 2/3 |
| t2-why-ndfla-filings-halved-fy2024 | 2/3 |
