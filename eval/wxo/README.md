# eval/wxo

## Agent instruction versions

`instructions/v0.txt`–`v3.txt` are the **courts-analyst-syed** agent instruction versions used in the tuning rounds:

| File | Description |
|------|-------------|
| `v0.txt` | Step 03 text (baseline) |
| `v1.txt` | + explanation rules |
| `v2.txt` | + policy and decline rules — **final version** |
| `v3.txt` | + measure-choice rule (reverted) |

## Test cases

`tests/l1/` and `tests/l1desk/` are **orchestrate evaluations** test cases.

**Run:**
```
orchestrate evaluations evaluate -p eval/wxo/tests/l1 -o eval/wxo/out
```

Recording new test cases requires `AGENT_NAME=Untitled_Agent_1_6636bi`.

> Output is written to `eval/wxo/out/` which is git-ignored — commit a run deliberately with `git add -f` if needed.
