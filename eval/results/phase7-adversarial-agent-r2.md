### agent-sonnet-5 · adversarial-both

**43/47 correct (91.5%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 47 | 43 | 91.5% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 47 | 45 | 95.7% |
| claim | 28 | 26 | 92.9% |
| edition | 13 | 12 | 92.3% |
| numeric | 13 | 12 | 92.3% |
| revision | 3 | 3 | 100.0% |
| tools | 16 | 14 | 87.5% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 87.5% | 100.0% | 14 |
| clarify | 100.0% | 50.0% | 2 |
| decline | 100.0% | 96.8% | 31 |

| Error category | Count |
| --- | ---: |
| argument | 1 |
| output_interpretation | 1 |
| task_understanding | 1 |
| tool_selection | 1 |

Latency p50 4.76 s, p95 9.72 s.

Model cost $1.6665 ($0.0355 per question).
