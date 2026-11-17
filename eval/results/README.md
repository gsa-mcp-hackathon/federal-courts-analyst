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
| `20261114T163434Z-wxo-all-dev-subset` (+ `-rescored`, `-rescored-digits`) | IBM step 09 | **wxO baseline**, full dev split (117 items on the agent's tools), v7, 3 repeats: mean 85.8% (81.7–89.0), pass^3 79.5%; re-scored with infra tagging: 13 of 351 attempts hit wxO tool-runtime errors |
| `20261114T180426Z-wxo-all-dev-subset` (+ `-rescored`, `-rescored-digits`) | IBM step 09 | Round 1, v8 (neutrality), **kept**: 86.3% (82.3–89.5), pass^3 75.2%, 0 preview violations |
| `20261114T211211Z-wxo-all-dev-subset` (+ `-rescored-digits`) | IBM step 09 | Round 2, v9 (clarify rule last), rejected: 86.9% (83.0–90.0); one preview violation in the desk test |
| `20261114T224945Z-wxo-all-dev-subset` (+ `-rescored-digits`) | IBM step 09 | Round 3, v10 (clarify first, retry preview), not kept: 86.6% (82.6–89.8), pass@3 94.9%; `adv-defendant-names-sample` 2/3 → 0/3 |
| `20261115T005938Z-wxo-all-dev-subset` (+ `-rescored-digits`) | IBM step 09 | Round 4, v11, rejected: 84.3% (80.2–87.8); three preview violations in the desk test |
| `20261115T025353Z-wxo-all-test2-subset` (+ `-rescored-digits`) | IBM step 09 | **Held-out test2 (45 items), run once**, v8: mean 80.0% (72.5–85.9), pass@3 86.7%, pass^3 73.3%, 9 of 135 attempts hit tool-runtime errors |
| `wxo-l1-2026-11-14/` | IBM step 09 | Layer 1 desk-test transcripts (`orchestrate evaluations`) for each round above; `courts-eval preview-check` reads these folders |
| `20261116T005129Z-wxo-all-dev-subset` (+ `-rescored-digits`) | IBM step 10 | **Dev on the deployed server** (159f529), v8: 85.2% (81.1–88.5), pass^3 73.5% as scored; **88.3% (84.5–91.3), pass^3 80.3%** re-scored; 11 of 351 attempts hit tool-runtime errors |
| `20261117T041215Z-wxo-all-dev-subset` | 2026-11-17 | **Dev with the case-level tools**: draft agent, v8, 12 tools from the compact-IDB toolkit `courts_analyst_syed_idb`, preset `wxo-idb` (125 items). On the 117 items shared with the deployed-dev run: 92.9% (89.7–95.1), pass^3 88.9%, 4 infra errors; the 8 items that need a case tool: 17/24; all 125: 91.5% (88.2–93.9), pass^3 86.4%. Engine 63/63, every attempt via `reconcile`. 0 preview violations |
| `20261116T022346Z-wxo-all-dev-subset` (+ `-rescored-digits`) | IBM step 10 | v13 candidate, not kept: 87.5% as scored, 89.5% re-scored; `explain-direct-filed-mdl` 3/3 → 0/3 |
| `wxo-l1-2026-11-15/`, `wxo-l1-2026-11-16/` | IBM step 10 | Layer 1 desk transcripts on the deployed server: `v8-pr9`, `v8`, `v12`, `v8-pr12`; v13 |
| `*-rescored-digits` | IBM step 10 | Re-scored 2026-11-16 after the scorer learned to read a narrow no-break space (U+202F) between digit groups as a thousands separator ("297 877"); the replies are unchanged |
| `write-safety` (`.md`, `.json`) | 9b | Request desk write-safety suite on the full catalog (`make eval-write-safety`): 22 of 22 cases pass; regenerated 2026-11-16 |
| `20261115T025353Z-wxo-all-test2-subset-rescored-md` | 2026-11-16 | Held-out test2 re-scored after phrase checks learned to ignore markdown emphasis ("**7** additional"): 81.5% (74.1–87.1), pass^3 75.6%. Found while reading held-out replies against the LLM judge, so the headline stays 80.0%. Every dev run was re-scored too and none changed (not committed) |
| `baseline-dev-claude-sonnet-server` / `baseline-dev-claude-sonnet-notools` | 2026-11-16 | No-tool baseline: Claude Sonnet (headless Claude Code) on the 117 dev items of the wxO subset, one attempt each, with this server (`claude-code`): 109/117; with no tools (`claude-code-notools`): 22/117. Without tool selection: 93.5% against 20.6% |
| `llm-judge-wxo-v8` (`.md`, `.jsonl`) | 2026-11-16 | `courts-eval judge` over the held-out and deployed-dev wxO replies (486) plus 340 known-wrong edits, with the `generic` and `informed` prompts; held-out graded twice for consistency. Agreement 96.7% / 97.1%; 1,922 judge calls, $12.86 at list prices |
| `desk-flows-claude-sonnet` (`.md`, `.jsonl`) | 2026-11-16 | `courts-eval desk-flows`: scripted request-desk conversations, Claude Sonnet on the full server, 5 scenarios × 3 runs, step-by-step write tools (`step`) vs `keep_answer` (`keep`). step 9/15 (every save conversation wrote before a yes), keep 15/15 |
