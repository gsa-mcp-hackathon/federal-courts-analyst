# Evaluation

The benchmark that every phase after Phase 3 is measured against: a question
bank with known answers, deterministic scorers (no LLM judge scores a number),
and a runner that works with any system that can answer a question.

| Path | What |
| --- | --- |
| [`questions/`](questions/) | The bank: one YAML file per suite |
| `results/` | Run outputs (gitignored; phase baselines are committed on purpose) |
| [`wxo/`](wxo/) | The watsonx Orchestrate agent: instruction versions, Layer 1 desk tests, `run_eval.sh` |
| [`SUMMARY.md`](SUMMARY.md) | One-page evaluation summary for the submission |
| [`databricks/`](databricks/) | The GSA template's Databricks MLflow kit (Phase 10) |
| [`src/courts_analyst/evaluation/`](../src/courts_analyst/evaluation/) | Schema, scorers, answerers, runner, CLI |

## Quick start

```bash
make eval-validate                      # schema, unique ids, split share
make eval                               # harness self-check: gold 100%, null 0%
uv run courts-eval stats                # counts by suite, split and tag
uv run courts-eval run --answerer gold --suite e2e --split dev
uv run courts-eval show eval/results/<run_id>.summary.json
make eval-claude                        # the 20-question smoke set with Claude
uv run courts-eval run --answerer claude-code --suite e2e --split dev --workers 4
uv run courts-eval rescore eval/results/<run_id>.jsonl   # re-score saved answers
```

A run writes `<run_id>.jsonl` (each answer record and its score),
`<run_id>.summary.json` and `<run_id>.md` to `eval/results/`.

## Reproduce the watsonx Orchestrate evaluation

The submitted agent is `courts-analyst-syed` on watsonx Orchestrate with this
server registered as a local MCP toolkit (8 tools). One script reproduces
each published number (see [`wxo/README.md`](wxo/README.md) for setup):

```bash
eval/wxo/run_eval.sh dev                  # dev split: 117 items x 3 repeats
DESK=1 eval/wxo/run_eval.sh heldout       # test2 held-out split, once, plus the three desk tests
```

It checks the live agent's instructions and tools against
`eval/wxo/instructions/v8.txt`, writes provenance into the run summary,
scores the run, and fails on any request-desk preview violation. The runs
behind [`SUMMARY.md`](SUMMARY.md) are committed under `results/` (listed in
[`results/README.md`](results/README.md)); `uv run courts-eval show
results/<run_id>.summary.json` and `uv run courts-eval preview-check
results/<run_id>.jsonl results/wxo-l1-2026-11-14/<dir>` re-derive them
without the agent.

## The bank

| Suite | Items | What it tests | Correct when |
| --- | ---: | --- | --- |
| `engine` | 30 | IDB-derived filings, terminations and pending vs Table C-1 | Within the item's relative tolerance |
| `e2e` | 66 | Factual questions with official answers (national, district, circuit; rankings; IDB cohorts) | Every expected value, attributed to a correct edition; revisions flagged |
| `explanation` | 26 | "Why" questions (the FY2020 jump, the 554 → 322 revision, definitions) | Every rule-based claim holds |
| `tool_selection` | 30 | Which tool(s) a model picks from the descriptions alone | Every expected tool was called |
| `adversarial` | 79 | Judge rankings, party names, advocacy, out-of-scope years and periods, small cells, prompt injection, mixed editions, ambiguity, and over-refusal controls that must be answered | The right behaviour (answer / clarify / decline) plus its claims |

Every expected official figure carries a `ref` to the catalog cell it came from
(measure, court, fiscal year, edition). `tests/test_question_schema.py` checks
each value, and every edition listed as acceptable, against the catalog built
from the committed fixtures, and recomputes every expected ranking. The few
IDB-derived figures (cohort counts and medians) are labelled `IDB-derived`,
carry a relative tolerance and note the release they came from.

The 231 items (152 in the original bank, then 34 more dev and test items and
the 45-item `test2` split) were drafted with Claude from the catalog and the
IDB, following the plan's list of edition traps and the demo storyline. The
tests above check every expected number and edition against the catalog, so
no item carries a wrong figure. Whether each question is the one a court
analyst would ask, and the wording of the expected explanation claims, haven't
had an outside domain expert's review; [`EVALUATION.md`](EVALUATION.md) lists
this under limitations.

### Smoke set

Model runs cost money, so the default is a fixed **smoke set** of 25
questions tagged `smoke` (`--tag smoke`, `make eval-claude`): 6 factual, 4
explanation, 5 tool-selection and 10 adversarial, all from the `dev` split,
together calling every tool and covering the main traps (554 vs 322, the
FY2017 pending restatement, judge rankings, party names, prompt injection,
policy framing, small cells). The five additional adversarial items cover
out-of-scope declines (years before the tables, bankruptcy, calendar periods)
and over-refusal controls. `tests/test_question_schema.py` keeps it small,
dev-only and covering every tool. Run the full bank only at the end of a
phase and for the final evaluation.

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
- **Behaviour.** Declared; else "answered" when the expected figures are
  there; else our tools' `status` (`needs_clarification`, `declined`) and
  phrase rules (strong refusal phrases anywhere, weaker ones only in an
  answer's opening, then clarifying questions). Reported as a confusion matrix
  with precision and recall for answer, clarify and decline. The phrase rules
  are unit-tested against real transcripts; `courts-eval rescore` re-scores a
  saved run after a scorer change, without asking the model again.
- **Tools.** Every expected tool must be called. It decides correctness only in
  `tool_selection`; elsewhere it's a diagnostic.
- **Error taxonomy** (MCP-Atlas style), one per failure: `tool_selection`,
  `argument`, `task_understanding`, `hallucinated_number` (an edition-attributed
  number that no tool output contains), `output_interpretation`,
  `answerer_failure`.

**LLM judge, for comparison only.** `courts-eval judge <run>.jsonl --out
results/<name>` re-grades a saved run with an LLM judge (Claude through
`claude -p`, no tools) using two prompts: `generic`, the GSA template's
correctness judge, and `informed`, which adds this domain's rules. It also
grades known-wrong edits of passing replies (swapped editions, editions
removed, a value moved by 2) and reports agreement, Cohen's κ, catch rates
and every disagreement with the judge's reason. It never changes a score.
Results: [`EVALUATION.md`](EVALUATION.md), section 3.10.

## Answerers

Anything that implements `Answerer.answer(item) -> AnswerRecord` (final text,
tool calls with structured outputs, latency, tokens) can be evaluated.
Answerers other than `gold` must read only `item.question`.

| Name | What | Phase |
| --- | --- | --- |
| `gold` | Builds the expected answer from the item; must score 100% | 3 |
| `null` | Says nothing; must score 0% (every item has a check silence fails) | 3 |
| `engine` | Our analytics core computing the `engine` suite directly | 4 |
| `claude-code`, `claude-code-haiku` | Claude Sonnet / Haiku through headless Claude Code (`claude -p`), with every built-in tool off and only this MCP server connected; needs a logged-in `claude` CLI | 5 |
| `claude-code-notools` | No-tool baseline: Claude Sonnet with no tools and the same short prompt as its whole system prompt | 10 |
| `claude-api`, `claude-api-opus` | Claude Sonnet 5 / Opus 5 through the Messages API with this server's tools; prompt caching; **paid** | 5 |
| `openai-api` | GPT-5.6 Sol through the Responses API with this server's tools; **paid** | 5 |
| `agent`, `agent-openai` | The Phase 7 agent (the web app's answerer): same tools plus the request screen, the citation line for revised figures and the CourtListener fixture; **paid** (`make eval-agent-smoke`: 5 questions, $0.50 cap) | 7 |
| web search, Genie | Baselines | 10 |

**Paid answerers are fenced.** They run only on the smoke set (`--tag smoke`)
or a few `--id` values unless you pass `--allow-full-bank`, and every run has a
hard cap (`--budget-usd`, default $1): the budget is checked before every model
request, and once it's spent the remaining questions are recorded as
`answerer_failure: budget exhausted`. Each question is limited to 8 model
turns. Token counts and cost are recorded per answer and totalled in the run
summary (prices in `evaluation/budget.py`, with sources).

Measured on the smoke set (2026-09-27, 20 questions): Claude Sonnet 5 **$0.90
total, $0.045 a question**, 20/20; GPT-5.6 Sol **$0.19 total, $0.009 a
question**, 19/20. Most of Claude's cost is input: the nine tool definitions
(~14k tokens) go with every request, cached after the first. `make eval-api`
runs both.

## Held-out policy

- **Split.** An item is in the held-out `test` split when the first 32 bits of
  `sha256("split:" + id)` modulo 100 fall below 30; otherwise it's in `dev`.
  The split depends only on the id, so it can't drift when items are added,
  and `tests/test_split_stability.py` pins known assignments. Today 60 of
  the 186 dev and test items (32%) are in `test`, in every suite.
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
- **test2.** The `test` split was scored twice during the IBM track (steps 06
  and 08), so a fresh held-out set, `split: test2` (45 items, written before
  any agent run and generated reproducibly by `eval/wxo/gen_test2.py`), was
  added for the final run. `courts-eval` never selects it unless asked
  (`--split test2`); it was run once, with the final instructions (v8).
  `eval/results/.heldout-aece69f1ae6440c4` (the first 16 hex digits of v8's
  SHA-256) is committed, so `run_eval.sh heldout` with v8 stops on any clone
  unless `HELDOUT_AGAIN=1`.
