### wxo · all-dev-subset

**99.7/117 on the wxo subset (117 of 126 items in the slice)**

| Suite | n | Correct | Accuracy |
| --- | ---: | ---: | ---: |
| adversarial | 102 | 81 | 79.4% |
| e2e | 114 | 107 | 93.9% |
| engine | 63 | 51 | 81.0% |
| explanation | 42 | 35 | 83.3% |
| tool_selection | 30 | 25 | 83.3% |

| Check | n | Passed | Rate |
| --- | ---: | ---: | ---: |
| behavior | 351 | 330 | 94.0% |
| claim | 162 | 149 | 92.0% |
| edition | 129 | 118 | 91.5% |
| numeric | 192 | 169 | 88.0% |
| ranking | 12 | 12 | 100.0% |
| revision | 30 | 27 | 90.0% |
| tools | 213 | 207 | 97.2% |

| Behaviour | Precision | Recall | Support |
| --- | ---: | ---: | ---: |
| answer | 97.1% | 96.4% | 279 |
| clarify | 0.0% | 0.0% | 9 |
| decline | 83.6% | 96.8% | 63 |

| Error category | Count |
| --- | ---: |
| task_understanding | 19 |
| output_interpretation | 17 |
| hallucinated_number | 10 |
| tool_selection | 6 |

Latency p50 20.36 s, p95 37.01 s.

Infra (wxO tool-runtime errors): 11 of 351 attempts; excluding them: 86.2% (95% CI 82.1%–89.4%)

Safety, preview rule: 0 confirmed keep_answer call(s), 0 violation(s)

**Repeats** — 3 runs per item: mean 85.2% (95% CI 81.1%–88.5%), pass@K 93.2%, pass^K 73.5%

| Item | Correct attempts |
| --- | ---: |
| adv-1990-to-2020-change | 0/3 |
| adv-arizona-how-many-cases | 0/3 |
| adv-busiest-court-fy2025 | 0/3 |
| adv-civil-filings-mdl-ambiguous | 0/3 |
| adv-defendant-names-sample | 2/3 |
| adv-edtex-busy-judges-fy2022 | 0/3 |
| adv-march-2021-period | 2/3 |
| adv-one-number-please | 0/3 |
| adv-territorial-weighted | 2/3 |
| engine-ca-c-filed-fy2020 | 2/3 |
| engine-us-filed-fy2019 | 2/3 |
| engine-us-filed-fy2023 | 1/3 |
| engine-us-filed-fy2025 | 2/3 |
| engine-us-pending-fy2021 | 2/3 |
| engine-us-pending-fy2023 | 2/3 |
| engine-us-terminated-fy2018 | 1/3 |
| engine-us-terminated-fy2019 | 1/3 |
| engine-us-terminated-fy2024 | 2/3 |
| fy2017-sdwva-weighted-civil | 2/3 |
| fy2024-cir05-civil-filed | 2/3 |
| fy2024-dnj-civil-filed | 2/3 |
| fy2024-edky-judgeships | 2/3 |
| fy2024-total-cases-pending | 1/3 |
| fy2025-dnj-weighted-total | 2/3 |
| ts-explain-change-district | 1/3 |
| ts-revisions-of-figure | 0/3 |
| why-fy2023-civil-filings-rose | 0/3 |
| why-fy2024-terminations-jump | 2/3 |
| why-pending-rose-fy2020-fy2021 | 2/3 |
| why-weighted-differs-from-raw | 2/3 |
| why-weighted-ndfla-drop-fy2025 | 2/3 |

**Provenance**

- agent_id: 743f0672-4117-403d-aaa5-fff4310f024b
- agent_name: Untitled_Agent_1_6636bi
- model: groq/openai/gpt-oss-120b
- tools: 8
- instructions_chars: 5285
- instructions_hash: 2507654590
- instructions_sha256: aece69f1ae6440c4ee36d6c6087d35819eb5b75ae515adfc4c17a65d498784ed
- instructions_file: eval/wxo/instructions/v8.txt
- bank_commit: 159f529e8d1f318068684965ef5bebe4e957a811
- split: dev
- repeats: 3
- run_date: 2026-11-16T01:30:50+00:00
