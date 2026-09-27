# Evaluation

The benchmark that every phase after Phase 3 is measured against: a question
bank with known answers, deterministic scorers (no LLM judge scores a number),
and a runner that works with any system that can answer a question.

| Path | What |
| --- | --- |
| [`questions/`](questions/) | The bank: one YAML file per suite |
| `results/` | Run outputs (gitignored; phase baselines are committed on purpose) |
| [`databricks/`](databricks/) | The GSA template's Databricks MLflow kit (Phase 10) |
| [`src/courts_analyst/evaluation/`](../src/courts_analyst/evaluation/) | Schema, scorers, answerers, runner, CLI |

## Quick start

```bash
make eval-validate                      # schema, unique ids, split share
make eval                               # harness self-check: gold 100%, null 0%
uv run courts-eval stats                # counts by suite, split and tag
uv run courts-eval run --answerer gold --suite e2e --split dev
uv run courts-eval show eval/results/<run_id>.summary.json
```

A run writes `<run_id>.jsonl` (each answer record and its score),
`<run_id>.summary.json` and `<run_id>.md` to `eval/results/`.

## The bank

| Suite | Items | What it tests | Correct when |
| --- | ---: | --- | --- |
| `engine` | 30 | IDB-derived filings, terminations and pending vs Table C-1 | Within the item's relative tolerance |
| `e2e` | 51 | Factual questions with official answers (national, district, circuit; rankings; IDB cohorts) | Every expected value, attributed to a correct edition; revisions flagged |
| `explanation` | 20 | "Why" questions (the FY2020 jump, the 554 → 322 revision, definitions) | Every rule-based claim holds |
| `tool_selection` | 25 | Which tool(s) a model picks from the descriptions alone | Every expected tool was called |
| `adversarial` | 26 | Judge rankings, party names, out-of-scope years and periods, small cells, prompt injection, mixed editions, ambiguity | The right behaviour (answer / clarify / decline) plus its claims |

Every expected official figure carries a `ref` to the catalog cell it came from
(measure, court, fiscal year, edition). `tests/test_question_schema.py` checks
each value, and every edition listed as acceptable, against the catalog built
from the committed fixtures, and recomputes every expected ranking. The few
IDB-derived figures (cohort counts and medians) are labelled `IDB-derived`,
carry a relative tolerance and note the release they came from.

Questions were drafted by Claude from the catalog and the IDB, following the
plan's list of edition traps and the demo storyline. **They still need the
domain expert's review** (issue [#17](https://github.com/syedaun-techsur/federal-courts-analyst/issues/17)).

### Item format

```yaml
- id: fy2020-weighted-civil-national         # lowercase-kebab, unique
  question: What were weighted civil filings per judgeship nationally in FY2020?
  expected:
    behavior: answer                          # answer | clarify | decline
    figures:                                  # every one must be reported (figures_mode: all)
      - value: 322
        edition: [JFF-2023, JFF-2024, JFF-2025]   # any edition that prints this value
        ref: {measure: weighted_civil_filings_per_judgeship, court: US, fiscal_year: 2020, edition: JFF-2025}
        label: current official (latest edition)
      - value: 554
        edition: [JB-2020, JFF-2020, JFF-2021, JFF-2022]
        ref: {measure: weighted_civil_filings_per_judgeship, court: US, fiscal_year: 2020, edition: JB-2020}
        label: as first published
    must_mention_revision: true
  claims: []                                  # mentions / not_mentions / field / tool_called
  expected_tools: [get_official_figure]
  tags: [edition_trap, weighted, fy2020, demo, revised]
```

A revised figure asked for without an edition expects **both** the current and
the first-published value, following [ADR 0004](../docs/adr/0004-default-edition-policy.md).

## Scoring

All deterministic ([`scoring/`](../src/courts_analyst/evaluation/scoring/)):

- **Numeric.** A stated number matches when it equals the expected value at the
  printed precision (322 matches 322.2 and 321.6, not 321.4) or lies within the
  item's tolerance. Declared citations (`cited_figures`) are read first; prose
  is the fallback.
- **Edition.** Each number is paired with the nearest edition mention within 90
  characters, preferring one that follows it: `322 (JFF-2023)`, "Judicial
  Business 2020", "the 2023 edition of Judicial Facts and Figures". The right
  number with the wrong or no edition is wrong.
- **Claims.** Phrases in the final text, fields in structured tool outputs
  (`provenance[].revision_status`), or tools called.
- **Behaviour.** Declared, else inferred from our tools' `status`
  (`needs_clarification`, `declined`) and conservative phrases. Reported as a
  confusion matrix with precision and recall for answer, clarify and decline.
- **Tools.** Every expected tool must be called. It decides correctness only in
  `tool_selection`; elsewhere it's a diagnostic.
- **Error taxonomy** (MCP-Atlas style), one per failure: `tool_selection`,
  `argument`, `task_understanding`, `hallucinated_number` (an edition-attributed
  number that no tool output contains), `output_interpretation`,
  `answerer_failure`.

An LLM judge may later grade free-text explanation quality (Phase 10). It will
be reported separately, with its prompt in the repo, and never scores a number.

## Answerers

Anything that implements `Answerer.answer(item) -> AnswerRecord` (final text,
tool calls with structured outputs, latency, tokens) can be evaluated.
Answerers other than `gold` must read only `item.question`.

| Name | What | Phase |
| --- | --- | --- |
| `gold` | Builds the expected answer from the item; must score 100% | 3 |
| `null` | Says nothing; must score 0% (every item has a check silence fails) | 3 |
| `engine` | Our analytics core computing the `engine` suite directly | 4 |
| `claude-code` | Claude (headless Claude Code) with this MCP server | 5 |
| our agent, web search, Genie | Baselines | 7, 10 |

## Held-out policy

- **Split.** An item is in the held-out `test` split when the first 32 bits of
  `sha256("split:" + id)` modulo 100 fall below 30; otherwise it's in `dev`.
  The split depends only on the id, so it can't drift when items are added,
  and `tests/test_split_stability.py` pins known assignments. Today 49 of 152
  items (32%) are held out, in every suite.
- **Who looks at `test`.** Nobody tunes against it. Tool descriptions, prompts
  and the agent are tuned only on `dev` runs; `courts-eval run` without
  `--split` scores both, so pass `--split dev` while iterating.
- **When `test` is run.** At the end of a phase, to record a baseline
  (committed under `eval/results/`), and for the final evaluation (Phase 10).
  A test-split failure may be diagnosed, but a fix must be justified by a dev
  item or a general principle, never by the failing test item's wording.
- **Changing an item.** Fixing a wrong expected answer is allowed at any time
  (and recorded in the commit message). Rewording a `test` question to make a
  system pass isn't. Renaming an id moves it between splits, so don't rename.
