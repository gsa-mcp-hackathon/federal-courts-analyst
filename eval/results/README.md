# Eval results

Runs write here (`courts-eval run`): `<run_id>.jsonl` (every answer record and
its score), `<run_id>.summary.json` and `<run_id>.md`. The folder is gitignored;
phase baselines are committed deliberately with `git add -f` and listed below.

| Run | Phase | What |
| --- | --- | --- |
| `phase3-gold-all` / `phase3-null-all` | 3 | Harness self-check over all 152 items: gold 100%, null 0% |
| `phase4-engine` | 4 | Engine suite (30 IDB rebuilds vs Table C-1) answered by the analytics core on the full data: 30/30 |
| `phase5-*-sonnet-r1` (+ `-rescored`) | 5 | First Claude Sonnet run (headless Claude Code + this server) over tool_selection, e2e, explanation, adversarial; re-scored after the scorer fixes |
| `phase5-*-sonnet` (+ `-rescored`) | 5 | **Baseline for P6–P10**: second run after the description and `revision_notes` changes |
| `phase5-ts-all-haiku-r1` (+ `-rescored`) | 5 | Tool selection with Claude Haiku |
| `smoke-claude-api-sonnet-5` / `smoke-openai-api-gpt-5.6-sol` (+ `-rescored`) | 5 | Smoke set through the APIs: Sonnet 5 20/20 ($0.90), GPT-5.6 Sol 19/20 ($0.19) |
| `phase6-adversarial-sonnet` (+ `-rescored`) | 6 | 47-item adversarial suite after the guardrails, run 1: 34/47 as scored then, 43/47 re-scored (scorer phrases and three over-broad claims fixed) |
| `phase6-*-sonnet-r2` (+ `-rescored`) | 6 | **Phase 6 result**: run 2 after the citation and no-advocacy instructions. Adversarial 45/47 (decline P/R 32/32), e2e 51/51, explanation 20/20, tool selection 24/25 |
| `phase6-ts-judgeship-rerun` | 6 | `ts-judgeship-context-national` re-asked after the PII-scanner sentence-break fix: 1/1 |
| `phase7-agent-smoke5` | 7 | Live smoke: 5 smoke questions through the agent (`/api/ask`'s answerer, Claude Sonnet 5): 5/5, $0.15 |
| `phase7-e2e-dev-agent` (+ `-rescored`) | 7 | e2e dev split through the agent, prompt 2026-09-27.1: 36/38 as scored, 37/38 re-scored (Unicode hyphen in edition ids), $1.84 |
| `phase7-adversarial-agent` (+ `-rescored`) | 7 | Adversarial suite through the agent, prompt .1: 40/47 as scored, 44/47 re-scored (three scorer phrases), $1.58 |
| `phase7-adversarial-agent-r2` | 7 | **Phase 7 result**: adversarial after the prompt fix (.2): 43/47, dev 24/24, decline precision 100%; `adv-one-number-please` passes (issue #27), $1.67 |
