### openai-api-gpt-5.6-sol · all-both

**15/20 correct (75.0%)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 5 | 1 | 20.0% |
| e2e | 6 | 6 | 100.0% |
| explanation | 4 | 3 | 75.0% |
| tool_selection | 5 | 5 | 100.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 20 | 16 | 80.0% |
| claim | 13 | 11 | 84.6% |
| edition | 5 | 5 | 100.0% |
| numeric | 6 | 6 | 100.0% |
| ranking | 1 | 1 | 100.0% |
| revision | 1 | 1 | 100.0% |
| tools | 17 | 17 | 100.0% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 80.0% | 100.0% | 16 |
| clarify | — | — | 0 |
| decline | — | 0.0% | 4 |

| Error category | Count |
| --- | ---: |
| task_understanding | 4 |
| hallucinated_number | 1 |

Latency p50 8.41 s, p95 12.29 s.

Model cost $0.1880 ($0.0094 per question).
