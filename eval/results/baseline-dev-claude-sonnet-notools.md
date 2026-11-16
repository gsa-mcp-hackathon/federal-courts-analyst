### claude-code-sonnet-notools · all-dev-subset

**22/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 34 | 19 | 55.9% |
| e2e | 38 | 0 | 0.0% |
| engine | 21 | 0 | 0.0% |
| explanation | 14 | 3 | 21.4% |
| tool_selection | 10 | 0 | 0.0% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 117 | 27 | 23.1% |
| claim | 54 | 35 | 64.8% |
| edition | 43 | 0 | 0.0% |
| numeric | 64 | 1 | 1.6% |
| ranking | 4 | 0 | 0.0% |
| revision | 10 | 0 | 0.0% |
| tools | 71 | 0 | 0.0% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 80.0% | 8.6% | 93 |
| clarify | — | 0.0% | 3 |
| decline | 17.8% | 90.5% | 21 |

| Error category | Count |
| --- | ---: |
| tool_selection | 68 |
| task_understanding | 27 |

Latency p50 7.61 s, p95 9.92 s.

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)
