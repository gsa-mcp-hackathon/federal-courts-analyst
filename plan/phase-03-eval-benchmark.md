# Phase 3: Eval Benchmark v1

**Goal:** build the question bank and deterministic scorer **before** the tools, so every later phase is measured against it. Evaluation is about half of GSA's effort estimate and is where we can win.

**Judging impact:** Technical quality ("our own evaluation setup and results") and presentation ("evidence of testing").

## Scope

**In:** question bank, schema, deterministic scorers, held-out split, runner skeleton that can call any "answerer", CI smoke run.
**Out:** baselines, multi-model runs, MLflow/Phoenix dashboards (P10).

## Question bank

Stored as YAML under `eval/questions/`, one file per suite. Each item:

```yaml
id: fy2020-weighted-revised
suite: e2e            # e2e | tool_selection | adversarial | engine
split: dev            # dev | test (held out, never looked at while tuning descriptions)
question: "What were weighted civil filings per judgeship nationally in FY2020?"
expected:
  kind: numeric_with_edition
  answers:
    - value: 322
      edition: JFF-2023
      tolerance: 0
    - value: 554
      edition: JB-2020
  must_mention_revision: true
claims:                # checked deterministically by keyword/structured-field rules first
  - id: flags_revision
    rule: "response.provenance.revision_status in ['revised']"
expected_tools: [get_official_figure]
tags: [edition_trap, weighted, fy2020]
```

**Target size for v1:** about 150 items, 30% held out.

| Suite | Count | Examples |
| --- | --- | --- |
| Engine accuracy | 30 | IDB-computed filings by district/FY vs official C-3 |
| End-to-end factual | 50 | "Which 5 districts had the highest weighted filings per judgeship in FY2024?" |
| Explanation | 20 | "Why did civil filings jump in FY2020?" (claims: names N.D. Fla., names MDL, notes direct filing) |
| Tool selection | 25 | Map a question to the right tool(s) |
| Adversarial | 25 | Judge rankings, n < 30 cohorts, 554 vs 322, 673 vs 674, statistical vs fiscal year before 1993, out-of-scope years, prompt injection in docket text |

## Scoring (deterministic first, no LLM judge for numbers)

- **Numeric:** extract numbers from the **structured tool output or the final answer's cited provenance**, not by regex over prose where avoidable. Exact and within-tolerance scores.
- **Edition correctness:** an answer counts only if it names the right edition (or presents both when the question is ambiguous).
- **Claims:** rule-based checks over structured fields and required phrases; an LLM judge is allowed only for free-text explanation quality and is reported separately, with its prompt in the repo.
- **Refusal/clarification:** precision and recall for "should decline", "should ask", "should answer".
- **Error taxonomy:** MCP-Atlas style categories: tool selection error, argument error, task understanding error, output interpretation error, hallucinated number.

## Tasks

- [x] Pydantic schema for question items; validator script (`make eval-validate`)
- [x] Write v1 questions (drafted by Claude; domain expert review is [#17](https://github.com/syedaun-techsur/federal-courts-analyst/issues/17)); every expected official answer links to a table cell, checked against the catalog
- [x] Deterministic split assignment (hash of id) so the held-out set can't drift
- [x] Scorer library (numeric, edition, claims, refusal, taxonomy), in `courts_analyst.evaluation.scoring` (see Deviations)
- [x] `Answerer` protocol: `answer(question) -> AnswerRecord(final_text, tool_calls, structured_outputs, latency, tokens)`. Implementations come later (our agent, web-search baseline, Genie)
- [x] A `GoldAnswerer` (returns expected answers) and a `NullAnswerer` so the scorer can be tested now
- [x] Runner: `uv run courts-eval run --suite e2e --answerer <name> --split dev` writes `eval/results/<run_id>.jsonl` + summary JSON + Markdown
- [x] Nightly workflow: validates the bank and self-checks the harness (gold 100%, null 0%); the model smoke subset needs API key secrets (Phase 10, [#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18))

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_question_schema.py` | unit | Every YAML item validates; ids unique; every `expected` references a real golden figure |
| `test_scorer_numeric.py` | unit, hypothesis | Tolerance math; units (per judgeship vs totals); rounding |
| `test_scorer_edition.py` | unit | 322 with edition JB-2020 scores wrong; 322 with JFF-2023 scores right; giving both scores right when ambiguous |
| `test_scorer_refusal.py` | unit | Confusion-matrix math for decline/ask/answer |
| `test_gold_answerer.py` | integration | Gold answerer scores 100%; null answerer scores 0% (sanity check of the harness itself) |
| `test_split_stability.py` | unit | Split assignment is stable across runs and machines |

## Exit criteria

- [x] ~150 validated questions, 30% held out (152; 49 held out = 32%)
- [x] Gold/null answerers give 100%/0%
- [x] Runner writes results and a summary table
- [x] Held-out policy written in `eval/README.md` (who can look at test split items, and when)

## Risks

- Question writing is slow → start with the edition-trap and demo-storyline questions; grow the bank in P10.
- Overfitting tool descriptions to the questions → strict held-out split; tool descriptions tuned only on dev.

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| Scorers in `eval/scoring/`, runner `uv run eval run` | Package `courts_analyst.evaluation` (schema, bank, scoring, answerers, runner, CLI) under `src/`; data in `eval/questions/`; CLI `courts-eval` (`make eval`, `make eval-validate`) | Importable by tests and later phases without path hacks, and typed and coverage-gated like the rest. A console script named `eval` would shadow the shell builtin |
| `split: dev` written in each item | Split derived from `sha256("split:" + id)` and never stored (an item may state it, but then it must match) | The held-out set can't drift through a copy-paste or a hand edit |
| `expected.kind: numeric_with_edition` with `answers` | `expected` = `behavior` + `figures` (`figures_mode: all/any`) + `ranking` + `engine`; `edition` may be a **list** | One item can combine checks (a figure plus a revision flag plus a behaviour). A value printed identically in several editions (322 in JFF-2023, 2024 and 2025) is right with any of them |
| Claims as expressions (`"response.provenance.revision_status in ['revised']"`) | Typed rules: `mentions`, `not_mentions`, `field` (dotted path with `[]`), `tool_called`, `tool_not_called` | No `eval()` of strings from YAML; every rule is validated when the bank loads |
| "every `expected` references a real golden figure" | Every official figure carries a catalog `ref`; the test checks the value **and every acceptable edition** against the fixture catalog, and recomputes rankings. IDB-derived figures are labelled and carry a relative tolerance | The 56 golden figures are too few for 150 questions; the catalog is itself checked by golden figures and a 29,422-value xlsx/PDF cross-check |
| Suite counts 30/50/20/25/25 | 30 / 51 / 20 / 25 / 26 | One extra e2e (FY2019 and FY2020 filings together) and one extra clarify item, so `clarify` has more than one example |
| Nightly 20-question smoke subset | Nightly validates the bank and self-checks the harness; model runs wait for API key secrets | There are no model API keys in the repo or CI yet ([#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18)) |
| — | `--expect-accuracy` flag; `make eval` fails unless gold = 100% and null = 0% | Turns the harness self-check into a gate |
| — | `duckdb` and `pyyaml` moved from the `pipeline` group to runtime dependencies | The harness reads YAML, and the Phase 4 core reads DuckDB inside the server |

**Findings while writing the bank** (they feed Phase 4):

- The FY2017 national pending count was **restated by the AO**: 339,131 in JB-2017, 366,195 in JB-2018's prior-year column. That is most of the IDB's "+7.2%" variance in [#11](https://github.com/syedaun-techsur/federal-courts-analyst/issues/11): the IDB reconstruction is close to the restated figure.
- The weighted civil series in JFF-2018 carries a note ("Due to a change in methodology, numbers for years prior to 2015 may not match numbers previously published"), but nothing explains the 2023 revision.
- FY2024 is revised within the same year: JB-2024 prints 384 weighted civil filings per judgeship, JFF-2024 prints 335.
- JFF's FY2000 row has odd values in every edition (median time for civil cases with no court action 0.03 months, criminal bench trial 0.03). They're faithful to the workbooks; no question uses them.
