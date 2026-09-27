### claude-api-sonnet-5 · all-both

**19/20 correct (95.0%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 5 | 4 | 80.0% |
| e2e | 6 | 6 | 100.0% |
| explanation | 4 | 4 | 100.0% |
| tool_selection | 5 | 5 | 100.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 20 | 19 | 95.0% |
| claim | 13 | 13 | 100.0% |
| edition | 5 | 5 | 100.0% |
| numeric | 6 | 6 | 100.0% |
| ranking | 1 | 1 | 100.0% |
| revision | 1 | 1 | 100.0% |
| tools | 17 | 16 | 94.1% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 94.1% | 100.0% | 16 |
| clarify | — | — | 0 |
| decline | 100.0% | 75.0% | 4 |

| Error category | Count |
| --- | ---: |
| task_understanding | 1 |

Latency p50 7.11 s, p95 11.81 s.

Model cost $0.9019 ($0.0451 per question).
