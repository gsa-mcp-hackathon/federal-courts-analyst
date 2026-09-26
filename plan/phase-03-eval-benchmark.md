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

- [ ] Pydantic schema for question items; validator script (`make eval-validate`)
- [ ] Write v1 questions with the domain expert; every expected answer links to a golden figure or table cell
- [ ] Deterministic split assignment (hash of id) so the held-out set can't drift
- [ ] Scorer library `eval/scoring/` (numeric, edition, claims, refusal, taxonomy)
- [ ] `Answerer` protocol: `answer(question) -> AnswerRecord(final_text, tool_calls, structured_outputs, latency, tokens)`. Implementations come later (our agent, web-search baseline, Genie)
- [ ] A `GoldAnswerer` (returns expected answers) and a `NullAnswerer` so the scorer can be tested now
- [ ] Runner: `uv run eval run --suite e2e --answerer ours --split dev` writes `eval/results/<run_id>.jsonl` + summary
- [ ] Nightly workflow runs a 20-question smoke subset once tools exist

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

- [ ] ~150 validated questions, 30% held out
- [ ] Gold/null answerers give 100%/0%
- [ ] Runner writes results and a summary table
- [ ] Held-out policy written in `eval/README.md` (who can look at test split items, and when)

## Risks

- Question writing is slow → start with the edition-trap and demo-storyline questions; grow the bank in P10.
- Overfitting tool descriptions to the questions → strict held-out split; tool descriptions tuned only on dev.
