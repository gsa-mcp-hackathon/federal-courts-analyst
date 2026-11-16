# eval/wxo

## Agent instruction versions

`instructions/v0.txt`–`v13.txt` are the **courts-analyst-syed** agent instruction versions used in the tuning rounds:

| File | Description |
|------|-------------|
| `v0.txt` | Step 03 text (baseline) |
| `v1.txt` | + explanation rules |
| `v2.txt` | + policy and decline rules (final in step 06) |
| `v3.txt` | + measure-choice rule (reverted) |
| `v4.txt` | v2 + clarify/out-of-scope rules, decline limited to judges and parties, measure choice under rankings (reverted) |
| `v5.txt` | v2 + narrower out-of-scope (call the tool first) and clarify rules, prompt-injection/one-number rule |
| `v6.txt` | v5 + policy opener, 'always call get_official_figure first', out-of-scope list marked exhaustive (kept) |
| `v7.txt` | v6 + preview rule: the user's own keep request is not the yes, plain-words preview, one yes per keep_answer call (final in step 08) |
| `v8.txt` | v7 + neutrality: requests to argue a side (op-ed, letter, press release, talking points, "prove") get a decline with no figures; the "policy decision for Congress" opener only for a direct question — **final version** (step 09) |
| `v9.txt` | v8 + a clarify rule placed last in the list (rejected: one preview violation, clarify items barely moved) |
| `v10.txt` | v8 + clarify check first in the list, and a new preview on a retry after a refused save (not kept: `adv-defendant-names-sample` 2/3 → 0/3) |
| `v11.txt` | v10 + "which court was busiest" names no measure, refusals must give the reason (rejected: mean 84.3%, three preview violations) |
| `v12.txt` | v8 with rule 2 rewritten for the `preview_id` check (step 10): in the preview turn call keep_answer with confirm=false, then confirm with that preview_id after the yes; a refused save or changed text needs a new preview call and a new yes |
| `v13.txt` | v8 + one sentence in rule 3: after an error or `written: false`, no second `confirm=true` in that turn; start again from rule 2 (new preview, new "Shall I go ahead?"). Not kept: dev 87.5% (83.6–90.5%) but `explain-direct-filed-mdl` 3/3 → 0/3 |
| `found-live-2026-11-15.txt` | Not a tuning round: what was live on the agent on 2026-11-15 before the step 10 deploy (v8 + rules 5–7: preview for every desk write tool, no "judicial emergency" label for 600, no 【…】 tool fields), with 13 tools attached. Author unknown; replaced by v8 + the evaluated 8 tools (step 10) |

## Reproduce a run

```
set -a; source deploy/ibm/local-mcp-toolkit/.env; set +a      # WXO_INSTANCE_URL, WXO_ENV_NAME
read -rs -p 'key: ' WXO_API_KEY; export WXO_API_KEY            # never echo it
export WXO_AGENT_ID=<agent id>  AGENT_NAME=<internal agent name>
eval/wxo/run_eval.sh dev                                      # dev split, v8, 3 repeats
DESK=1 eval/wxo/run_eval.sh heldout                           # test2 once, plus the desk tests
DESK=1 eval/wxo/run_eval.sh dev                               # dev, plus the three desk tests
```

`run_eval.sh` checks the live agent against the instruction file with
`agent_check.py` (instructions, tool count; writes the provenance JSON the run
summary embeds), runs `courts-eval` with tools on the agent only, then
`courts-eval preview-check` over the run and, with `DESK=1`, over both Layer 1
desk transcripts. It exits 1 on a mismatch or any preview violation. A second
held-out run with the same instructions stops unless `HELDOUT_AGAIN=1`.

## Test cases

`tests/l1/`, `tests/l1desk/`, `tests/l1desk2/` (save, then my_requests status) and `tests/l1desk3/` (the first save is refused for mixed editions, the user restates the text, and the agent must preview again before the second save) are **orchestrate evaluations** test cases.

`keep_answer` takes a `preview_id`: the `confirm=false` call returns one, and the `confirm=true` call must pass it for the same answer, option, asker and citations (ADR 0013). Each id works once, so `l1desk3` expects two preview calls and two confirmed calls. Journey Success doesn't check the preview rule; run `uv run courts-eval preview-check <outdir>` on every desk run.

**Run:**
```
orchestrate evaluations evaluate -p eval/wxo/tests/l1 -o eval/wxo/out
```

Recording new test cases requires `AGENT_NAME=Untitled_Agent_1_6636bi`.

> Output is written to `eval/wxo/out/` which is git-ignored — commit a run deliberately with `git add -f` if needed.
