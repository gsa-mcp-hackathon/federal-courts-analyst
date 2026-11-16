### claude-code-sonnet · all-dev-subset

**109/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 34 | 28 | 82.4% |
| e2e | 38 | 38 | 100.0% |
| engine | 21 | 21 | 100.0% |
| explanation | 14 | 13 | 92.9% |
| tool_selection | 10 | 9 | 90.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 117 | 110 | 94.0% |
| claim | 54 | 53 | 98.1% |
| edition | 43 | 43 | 100.0% |
| numeric | 64 | 64 | 100.0% |
| ranking | 4 | 4 | 100.0% |
| revision | 10 | 10 | 100.0% |
| tools | 71 | 71 | 100.0% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 96.8% | 97.8% | 93 |
| clarify | — | 0.0% | 3 |
| decline | 82.6% | 90.5% | 21 |

| Error category | Count |
| --- | ---: |
| task_understanding | 7 |
| hallucinated_number | 1 |

Latency p50 5.04 s, p95 8.22 s.

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)
