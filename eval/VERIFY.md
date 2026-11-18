# Checking our evaluation yourself

A guide for judges and reviewers: how to check every number in
[`EVALUATION.md`](EVALUATION.md) without taking our word for it.

**Why you can't just ask our agent.** The evaluated agent runs on a private
watsonx Orchestrate trial instance, and the hackathon rules mean we expose no
public endpoint. So we made the evaluation checkable another way:

- **Every reply is committed.** Each run in [`results/`](results/README.md)
  holds, for every question and repeat, the agent's full reply, every tool
  call with its arguments and output, latency, tokens and the score.
- **The scoring is code**, with no LLM judge. Anyone can re-run it on the
  saved replies and get the same numbers.

Pick the level that suits the time you have. Levels 1 and 2 need no data,
no keys and no accounts.

| Level | What you check | Needs | Time |
| --- | --- | --- | --- |
| [1. Read](#level-1-read-the-saved-replies) | What the agent actually said, and why each reply passed or failed | A browser | Minutes |
| [2. Re-derive](#level-2-re-derive-our-numbers-no-data-no-keys) | Every headline number, from the saved replies | `git`, [`uv`](https://docs.astral.sh/uv/) | ~5 min |
| [3. Build the data](#level-3-build-the-data-and-run-the-server-checks) | The write-safety suite, the server itself | Internet access to uscourts.gov | ~5 min |
| [4. Your own model](#level-4-run-the-question-bank-with-your-own-model) | The same bank and scorer on a model you control | A `claude` login or an API key | Varies |
| [5. watsonx Orchestrate](#level-5-reproduce-the-watsonx-orchestrate-runs) | The whole Orchestrate evaluation, on your own instance | A watsonx Orchestrate account | Hours |

## Setup (levels 2 to 4)

```bash
git clone https://github.com/gsa-mcp-hackathon/federal-courts-analyst
cd federal-courts-analyst
uv sync --group dev
```

## Level 1: read the saved replies

Start with these runs. Each has three files: `<run>.md` (a readable report
with per-item results), `<run>.summary.json` and `<run>.jsonl` (one record
per question and repeat).

| Run | What it is | Result |
| --- | --- | --- |
| [`20261115T025353Z-wxo-all-test2-subset`](results/20261115T025353Z-wxo-all-test2-subset.md) | **Held-out test2**, 45 items × 3, scored once | **80.0%** |
| [`20261116T005129Z-wxo-all-dev-subset-rescored-digits`](results/20261116T005129Z-wxo-all-dev-subset-rescored-digits.md) | Dev, 117 items × 3, the deployed 8-tool configuration | 88.3% |
| [`20261117T172544Z-wxo-all-dev-subset`](results/20261117T172544Z-wxo-all-dev-subset.md) | Dev on Live 1.2.0 (12 tools, with the case-level tools) | 88.6% on the shared 117 items |
| [`write-safety.md`](results/write-safety.md) | The request desk's 22 refuse-or-allow cases | 22/22 |
| [`llm-judge-wxo-v8.md`](results/llm-judge-wxo-v8.md) | Our scorer against an LLM judge, with 340 planted errors | Section 3.10 |
| `wxo-l1-2026-11-14/` to `wxo-l1-2026-11-17/` | Transcripts of the multi-turn desk tests (IBM's `orchestrate evaluations`) | Section 3.3 |

[`results/README.md`](results/README.md) lists every committed run, including
the instruction versions we tried and rejected.

**One record, explained.** Each line of a `.jsonl` file is one attempt:

| Field | What it holds |
| --- | --- |
| `question` | What was asked |
| `record.final_text` | The agent's reply, verbatim |
| `record.tool_calls` | Each tool the agent called, with arguments and the server's output |
| `record.latency_s`, `record.input_tokens`, `record.output_tokens` | Cost of the attempt |
| `score.correct` | Pass or fail |
| `score.checks` | Each check and its result: numbers, edition labels, claims, behaviour, tools |
| `score.expected_behavior`, `score.actual_behavior` | `answer`, `clarify` or `decline` |
| `score.error_category`, `score.infra_error` | Why it failed; whether the Orchestrate tool runtime failed rather than the agent |

For example, the first held-out record asks "Which district court was the
busiest in FY2019?". The item expects the agent to **clarify** (busiest by
which measure?); the agent **answered**, so it fails. That is the weakness
we report in section 3.6 of [`EVALUATION.md`](EVALUATION.md).

The question bank itself, with every expected answer and its source, is in
[`questions/`](questions/), one YAML file per suite.

## Level 2: re-derive our numbers (no data, no keys)

Each command below runs in a few seconds on a fresh clone. The right-hand
column is what you should see.

| Command | Checks | Expected output |
| --- | --- | --- |
| `uv run courts-eval validate` | The bank's schema, unique ids and splits | `238 questions valid; ... 45 test2` (the 231 items in `EVALUATION.md` plus the 7 case-types-in-words items added for Live 1.2.0) |
| `uv run courts-eval show eval/results/20261115T025353Z-wxo-all-test2-subset.summary.json` | The held-out headline as recorded | `108/135 correct (80.0%)`, e2e 42/42, edition 42/42 |
| `uv run courts-eval rescore eval/results/20261115T025353Z-wxo-all-test2-subset.jsonl --results-dir /tmp/rescore` | Our current scorer on the saved held-out replies | `110/135 correct (81.5%)` |
| `uv run courts-eval rescore eval/results/20261116T005129Z-wxo-all-dev-subset.jsonl --results-dir /tmp/rescore` | The same for dev | `310/351 correct (88.3%)` |
| `uv run courts-eval preview-check eval/results/wxo-l1-2026-11-14` | Desk transcripts **before** the server-side check | `18 confirmed keep_answer call(s), 8 violation(s)` |
| `uv run courts-eval preview-check eval/results/wxo-l1-2026-11-15/v8-pr12` | The deployed configuration | `14 ... 3 violation(s)` |
| `uv run courts-eval preview-check eval/results/wxo-l1-2026-11-17/idb-12tools` | The 12-tool configuration | `14 ... 1 violation(s)` |
| `uv run python eval/wxo/compare_runs.py eval/results/20261117T041215Z-wxo-all-dev-subset.jsonl eval/results/20261117T172544Z-wxo-all-dev-subset.jsonl --shared-with eval/results/20261116T005129Z-wxo-all-dev-subset-rescored-digits.summary.json` | The two 12-tool dev runs, item by item | `92.9%` and `88.6%` on the shared 117 items, then each item that changed |
| `make eval` | The harness grades itself: perfect answers must pass, silence must fail | `193/193 correct (100.0%)`, then `0/193 correct (0.0%)` |

What these show:

- **Held-out 80.0% vs 81.5%.** The re-score is higher because of a later
  scorer fix (markdown bold hid "**7** additional"). We found it while
  reading held-out replies, so the headline stays at the first score, 80.0%
  ([`EVALUATION.md`](EVALUATION.md) 3.1 and 3.6).
- **Violations aren't saves.** A preview violation is the agent trying to
  save without asking again. Since the server-side check, the server refused
  every one, so nothing was saved without the user's yes (3.3).
- **Re-scoring never re-asks the agent.** Replies are fixed; only the scorer
  runs. That is how scorer fixes were applied to old runs without changing
  any answer.

## Level 3: build the data and run the server checks

```bash
make data-tables        # downloads the official uscourts.gov tables (~7 MB, about 4 minutes), checks their sha256 pins, builds data/build/courts.duckdb
make eval-write-safety  # 22 attempts the request desk must refuse or allow
```

`make eval-write-safety` should print **22 of 22 passed** and write
`eval/results/write-safety.md`. The cases include mixed editions, invented
numbers, wrong edition labels, advocacy, the agent approving its own
answer, judge and party requests, prompt injection and hidden characters
(section 3.3).

With the data built you can also run the server and ask it questions from
your own MCP client: see [`QUICKSTART.md`](../QUICKSTART.md).
`make test` runs the unit, protocol and container tests; they use committed
fixtures and need no download.

The case-level tools (`find_cases`, `analyze_cohort`, `sample_dockets`,
`reconcile`) and the `engine` suite also need the FJC civil database:
`make data-idb` downloads about 330 MB and builds it in a couple of minutes.

## Level 4: run the question bank with your own model

The harness isn't tied to watsonx Orchestrate. Any model that can call this
server's tools can be put through the same bank and scorer. Build the data
first (level 3).

```bash
make eval-claude    # the 20-question smoke set, Claude through a logged-in `claude` CLI
uv run courts-eval run --answerer claude-code --suite e2e --split dev --workers 4
uv run courts-eval run --answerer claude-code-notools --suite e2e --split dev   # the no-tool baseline (3.9)
```

The API answerers (`claude-api`, `openai-api`) need a key in `.env` and are
fenced: they run only the smoke set unless you pass `--allow-full-bank`, and
every run stops at `--budget-usd` (default $1). Answerers and their options:
[`README.md`](README.md#answerers).

What to expect, from our own runs: Claude Sonnet with the server scored
93.5% on the 117 dev items, and 20.6% without it (3.9).

## Level 5: reproduce the watsonx Orchestrate runs

On your own watsonx Orchestrate instance:

1. Register the server as a local MCP toolkit:
   [`deploy/ibm/local-mcp-toolkit/README.md`](../deploy/ibm/local-mcp-toolkit/README.md)
   (`register-toolkit.sh`; set `INCLUDE_IDB=1` for the case-level tools).
2. Create an agent with model `groq/openai/gpt-oss-120b`, the instructions in
   [`wxo/instructions/v8.txt`](wxo/instructions/v8.txt), and the 8 evaluated
   tools: `get_official_figure`, `explain_change`, `compare_courts`,
   `judgeship_context`, `explain_term`, `check_inquiry_eligibility`,
   `keep_answer` and `my_requests`.
3. Set `WXO_INSTANCE_URL`, `WXO_API_KEY`, `WXO_AGENT_ID` and `AGENT_NAME`
   as in [`wxo/README.md`](wxo/README.md#reproduce-a-run), then run
   `eval/wxo/run_eval.sh dev`. It first checks that the agent's instructions
   and tools match the files, records the configuration in the run's
   summary, scores the run and fails on any preview violation. `DESK=1`
   adds the three multi-turn desk tests.

A dev run is 351 questions at about 20 seconds each. Please don't run
`heldout`: test2 is scored once, and the script refuses a second run with
the same instructions.

## What you can't check from here

- **The live agent itself.** We describe what's on the instance (version
  history, the 6 tests on IBM's Evaluate page, 6/6) in
  [`EVALUATION.md`](EVALUATION.md) 3.7 and [`SUMMARY.md`](SUMMARY.md). The
  evidence for accuracy and safety is the committed runs above, not that page.
- **That the replies came from our agent.** Each wxO run's summary records the
  agent, model, instruction hash and repository commit it ran against
  (the `provenance` block; the held-out run predates it, and its
  configuration is in [`EVALUATION.md`](EVALUATION.md) 3.1). Level 5 is the
  way to produce such replies yourself.
