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
