# eval/wxo

## Agent instruction versions

`instructions/v0.txt`–`v7.txt` are the **courts-analyst-syed** agent instruction versions used in the tuning rounds:

| File | Description |
|------|-------------|
| `v0.txt` | Step 03 text (baseline) |
| `v1.txt` | + explanation rules |
| `v2.txt` | + policy and decline rules (final in step 06) |
| `v3.txt` | + measure-choice rule (reverted) |
| `v4.txt` | v2 + clarify/out-of-scope rules, decline limited to judges and parties, measure choice under rankings (reverted) |
| `v5.txt` | v2 + narrower out-of-scope (call the tool first) and clarify rules, prompt-injection/one-number rule |
| `v6.txt` | v5 + policy opener, 'always call get_official_figure first', out-of-scope list marked exhaustive (kept) |
| `v7.txt` | v6 + preview rule: the user's own keep request is not the yes, plain-words preview, one yes per keep_answer call — **final version** |

## Test cases

`tests/l1/`, `tests/l1desk/`, and `tests/l1desk2/` (save, then my_requests status) are **orchestrate evaluations** test cases.

**Run:**
```
orchestrate evaluations evaluate -p eval/wxo/tests/l1 -o eval/wxo/out
```

Recording new test cases requires `AGENT_NAME=Untitled_Agent_1_6636bi`.

> Output is written to `eval/wxo/out/` which is git-ignored — commit a run deliberately with `git add -f` if needed.
