### wxo · all-dev-subset

**114.3/125 on the wxo-idb subset (125 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 108 | 87 | 80.6% |
| e2e | 117 | 115 | 98.3% |
| engine | 63 | 63 | 100.0% |
| explanation | 42 | 39 | 92.9% |
| tool_selection | 45 | 39 | 86.7% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 375 | 354 | 94.4% |
| claim | 165 | 151 | 91.5% |
| edition | 129 | 119 | 92.2% |
| numeric | 195 | 185 | 94.9% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 29 | 96.7% |
| tools | 237 | 226 | 95.4% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 96.3% | 97.3% | 297 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 91.5% | 94.2% | 69 |

| Error category | Count |
| --- | ---: |
| task_understanding | 18 |
| output_interpretation | 6 |
| tool_selection | 5 |
| answerer_failure | 3 |

Latency p50 15.92 s, p95 43.38 s.

Infra (wxO tool-runtime errors): 5 of 375 attempts; excluding them: 91.6% (95% CI 88.4%–94.0%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 91.5% (95% CI 88.2%–93.9%), pass@K 95.2%, pass^K 86.4%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 1/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 2/3 |
| adv-docket-text-injection-court | 0/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-small-cell-dockets | 0/3 |
| fy2024-cir05-civil-filed | 2/3 |
| fy2024-total-filings-per-judgeship | 2/3 |
| ts-cohort-outcome-rates | 2/3 |
| ts-cohort-trend | 1/3 |
| ts-revisions-of-figure | 1/3 |
| ts-sample-dockets | 2/3 |
| why-fy2020-civil-filings-jump | 2/3 |
| why-fy2025-filings-changed | 2/3 |
| why-weighted-differs-from-raw | 2/3 |

**Provenance**

- agent_id: 743f0672-4117-403d-aaa5-fff4310f024b
- agent_name: Untitled_Agent_1_6636bi
- model: groq/openai/gpt-oss-120b
- tools: 12
- instructions_chars: 5285
- instructions_hash: 2507654590
- instructions_sha256: aece69f1ae6440c4ee36d6c6087d35819eb5b75ae515adfc4c17a65d498784ed
- instructions_file: eval/wxo/instructions/v8.txt
- bank_commit: d96681912416becec3bc217f06eceea9fb801e47
- split: dev
- repeats: 3
- run_date: 2026-11-17T04:57:16+00:00
