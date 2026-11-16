# Phase 10: Full Evaluation

**Goal:** produce the headline results: accuracy lift of our server over (a) the same model with web search and (b) a Databricks Genie space over identical tables, across several models, measured on the held-out split with deterministic scoring and tracked in MLflow and Phoenix.

**Judging impact:** Technical quality (about half the expected effort) and presentation (the demo's closing slide).

## Experiment design

| Arm | Description |
| --- | --- |
| **Ours** | Agent + Federal Courts Analyst MCP (+ CourtListener where relevant) |
| **Web search** | Same model and system-prompt style, web search tool only, no MCP |
| **Genie** | Databricks Genie space over the same official tables and IDB subset in Unity Catalog, with a reasonable instruction set (we document it so the comparison is fair) |
| **Ours, no guardrails** (ablation) | Guardrail layer disabled, to show what the guardrails buy on the adversarial suite |
| **Ours, no provenance hints** (ablation, stretch) | Strips `suggested_next` and revision info, to show what the design adds |

**Models:** at least two families, for example Claude (default), an OpenAI model (partner), and an open model served on Databricks (stretch).

**Runs:** each (arm × model × suite) run 3 times to report variance. Held-out `test` split for headline numbers; `dev` numbers reported separately.

## Metrics

| Suite | Metrics |
| --- | --- |
| Engine accuracy | Variance per table/period; % within tolerance; explained vs unexplained gaps (links to the variance report) |
| End-to-end | Exact accuracy, within-tolerance accuracy, **edition-correct accuracy** (headline), hallucinated-number rate |
| Explanation | Claims satisfied (deterministic); LLM-judge quality score reported separately with its prompt |
| Tool selection | Correct first tool, correct tool set, argument validity, across models |
| Adversarial | Decline/clarify/answer precision and recall; guardrail ablation delta |
| Performance | p50/p95 latency per tool and per end-to-end answer; graceful-failure rate under injected faults (DB timeout, CourtListener down) |
| Cost | Tokens and $ per answered question per arm |

Report 95% confidence intervals (bootstrap over questions) and a paired test (for example McNemar) for the lift claims, so we only claim differences that hold up.

## Tooling

- **MLflow** (template's Databricks kit): each run logged as an experiment with params (arm, model, split, prompt version, tool description hash, DB build hash), metrics and the per-item results artifact. Custom deterministic scorers wrap our `eval/scoring/`.
- **Phoenix:** OpenInference traces of every agent run; saved views for failed items grouped by error category. Screenshots for the eval doc.
- **Results dashboard:** the web app's Evaluation page (P8) reads `eval/results/summary.json`; a static export goes in the eval doc.

## Tasks

- [ ] Web-search answerer (same model, web tool only)
- [ ] Genie answerer via the Genie Conversation API; setup documented (tables, instructions, sample questions) in `eval/baselines/genie.md`
- [ ] Multi-model runner with retries, rate-limit handling, cost tracking, resumable runs
- [ ] MLflow logging + Phoenix tracing wired to the runner
- [ ] Fault-injection harness for the performance/graceful-failure suite
- [ ] Grow the question bank to ≥ 250 items (still 30% held out), prioritizing weak spots found on dev
- [ ] Error analysis: read every failure on dev, categorize, fix, re-run; log changes in `eval/CHANGELOG.md`
- [ ] Freeze: final tool descriptions + prompt version, then run the test split **once** for headline numbers
- [ ] Export charts and tables for the deck and eval doc

## Tests (of the eval harness itself)

| Test | Type | Checks |
| --- | --- | --- |
| `test_answerers_contract.py` | unit | All answerers return valid `AnswerRecord`s (recorded fixtures) |
| `test_runner_resume.py` | unit | Interrupted run resumes without duplicating items |
| `test_stats.py` | unit | Bootstrap CI and McNemar on known data |
| `test_mlflow_logging.py` | integration | A tiny run logs expected params/metrics to a local MLflow |
| `test_fault_injection.py` | integration | Injected faults produce graceful, typed errors, not crashes |
| `test_summary_schema.py` | unit | `summary.json` validates against the schema the web Evaluation page uses |

## Exit criteria

- [ ] Headline table: edition-correct accuracy for Ours vs Web search vs Genie, ≥ 2 model families, test split, with CIs
- [ ] Adversarial and guardrail ablation results
- [ ] Latency and cost table
- [ ] MLflow experiment and Phoenix project screenshots captured
- [ ] Evaluation page in the web app shows the final numbers

## Risks

- Genie access or cost → apply for workspace access early (P0/P9); if unavailable, report text-to-SQL over the same DuckDB tables with the same model as the substitute baseline and say so clearly.
- Model API budget → run dev on a small subset, full runs only at freeze; cache deterministic tool results.
- Honest results: if a baseline wins on some suite, we report it and explain. Candor reads well to judges.
