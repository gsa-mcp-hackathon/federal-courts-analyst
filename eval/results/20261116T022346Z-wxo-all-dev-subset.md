### wxo · all-dev-subset

**102.3/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 82 | 80.4% |
| e2e | 114 | 111 | 97.4% |
| engine | 63 | 52 | 82.5% |
| explanation | 42 | 34 | 81.0% |
| tool_selection | 30 | 28 | 93.3% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 337 | 96.0% |
| claim | 162 | 146 | 90.1% |
| edition | 129 | 121 | 93.8% |
| numeric | 192 | 174 | 90.6% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 27 | 90.0% |
| tools | 213 | 207 | 97.2% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 97.2% | 98.6% | 279 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 93.9% | 98.4% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 14 |
| output_interpretation | 12 |
| hallucinated_number | 12 |
| tool_selection | 5 |
| answerer_failure | 1 |

Latency p50 14.46 s, p95 28.83 s.

Infra (wxO tool-runtime errors): 1 of 351 attempts; excluding them: 87.4% (95% CI 83.5%–90.5%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 87.5% (95% CI 83.6%–90.5%), pass@K 94.0%, pass^K 79.5%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 1/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-blend-fy2021-weighted-total | 2/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 1/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-one-number-please | 0/3 |
| engine-us-filed-fy2016 | 2/3 |
| engine-us-filed-fy2023 | 1/3 |
| engine-us-filed-fy2025 | 2/3 |
| engine-us-pending-fy2019 | 2/3 |
| engine-us-pending-fy2021 | 2/3 |
| engine-us-pending-fy2023 | 2/3 |
| engine-us-pending-fy2025 | 2/3 |
| engine-us-terminated-fy2019 | 1/3 |
| engine-us-terminated-fy2020 | 2/3 |
| explain-direct-filed-mdl | 0/3 |
| fy2019-2020-civil-filed-change | 2/3 |
| fy2024-cir05-civil-filed | 2/3 |
| fy2024-total-cases-pending | 2/3 |
| ts-revisions-of-figure | 1/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-weighted-differs-from-raw | 1/3 |

**Provenance**

- agent_id: 743f0672-4117-403d-aaa5-fff4310f024b
- agent_name: Untitled_Agent_1_6636bi
- model: groq/openai/gpt-oss-120b
- tools: 8
- instructions_chars: 5490
- instructions_hash: 2555814257
- instructions_sha256: d94a85c50523d7e7b7766ae4601590904c1d260a309300cdff5de8960f8a24b9
- instructions_file: eval/wxo/instructions/v13.txt
- bank_commit: c60e439edb4d9a5fb40901526ea341a99b09db5e
- split: dev
- repeats: 3
- run_date: 2026-11-16T02:54:16+00:00
