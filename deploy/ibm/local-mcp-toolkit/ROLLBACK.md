# Shipping the civil IDB to watsonx Orchestrate, and rolling back

How to put the case-level tools (`find_cases`, `analyze_cohort`,
`sample_dockets`, `reconcile`) on the wxO agent by shipping the slim civil IDB
inside the local toolkit, and how to return to the evaluated setup. Nothing here
creates a public endpoint: the data travels inside the toolkit upload and the
server runs inside Orchestrate.

## What "the evaluated setup" is

The figures quoted in the README and `eval/EVALUATION.md` (dev 88.3% re-scored,
held-out test2 80.0%) were measured on this configuration. Check it before and
after any change.

| Part | Value |
|---|---|
| Agent | `courts-analyst-syed` (internal name in `eval/wxo/README.md`) |
| Instructions | `eval/wxo/instructions/v8.txt`: 5285 characters, hash 2507654590 (`eval/wxo/agent_check.py`) |
| Tools on the agent (8) | `get_official_figure`, `explain_change`, `compare_courts`, `judgeship_context`, `explain_term`, `check_inquiry_eligibility`, `keep_answer`, `my_requests` (`WXO_AGENT_TOOLS`) |
| Live version | 1.0.0, "v8 evaluated, submission" |
| Toolkit | `courts_analyst_syed`, 17 tools, **no IDB**, registered from `reference/request-desk` 159f529 |

The server and toolkit code at 159f529 is identical to `main` at 116349a; only
`src/courts_analyst/evaluation/` differs. To re-check:
`git diff --quiet 159f529 116349a -- src/courts_analyst ':!src/courts_analyst/evaluation' deploy/ibm/local-mcp-toolkit`.

**The IDB changes more than the four case tools.** When the IDB is present,
`explain_change` adds IDB breakdowns of a change (by nature of suit, origin,
court). With the IDB shipped, the agent is a new configuration, even with the
same 8 tools attached. Re-run the dev eval before quoting any figure for it.

## 0. Snapshot the live agent (before any change)

```bash
set -a; source deploy/ibm/local-mcp-toolkit/.env; set +a
# once per machine: orchestrate env add --name "$WXO_ENV_NAME" --url "$WXO_INSTANCE_URL" --type ibm_iam
read -r -s -p "API key (hidden): " K; echo
orchestrate env activate "$WXO_ENV_NAME" --api-key "$K"; unset K
S=deploy/ibm/local-mcp-toolkit/_snapshots          # git-ignored
mkdir -p "$S"
orchestrate agents export -n "$AGENT_NAME" -k native --agent-only \
  -o "$S/agent-$(date +%Y%m%d-%H%M).yaml"          # instructions + tool list
orchestrate agents list -v > "$S/agents.txt"
uv run python eval/wxo/agent_check.py "$S/agents.txt" "$WXO_AGENT_ID" \
  eval/wxo/instructions/v8.txt --tools 8 --out "$S/provenance.json"
COLUMNS=250 orchestrate toolkits list > "$S/toolkits.txt"
```

On the TechZone VM, `source ~/pre.sh v8` prints the same check (tools and
instruction hash).

## 1. Build and check the slim IDB

```bash
make data-idb          # full build, data/build/idb.duckdb (~440 MB)
make data-idb-slim     # data/build/slim/idb.duckdb (~66 MiB) + pii_index.bin
uv run pytest tests/test_idb_slim.py   # same rows; same tool answers as full
```

The register script zips the package before upload (ADK `ZIP_DEFLATED`), and
the size that counts is the zip. Refused with a 413: the 454 MB package with
the full IDB, and a first slim package (137 MB, ~61 MiB zipped, 2026-11-16).
~10 MB packages are accepted. The slim copy now stores the record table
compactly (a view over a narrower table, see `pipeline/idb/slim.py`): the
package is ~83 MB on disk and ~37 MiB zipped. The IDB is ~29 MiB of that, the
party-name index ~6 MiB, the tables catalog ~1 MiB.

## 2a. Recommended: a second toolkit next to the live one

Register the slim build under a **new** name. Nothing existing is removed, so
Live 1.0.0 and the evaluated toolkit stay as they are. The size test and the
deploy are the same step.

```bash
TOOLKIT_NAME=courts_analyst_syed_idb INCLUDE_IDB=1 \
  bash deploy/ibm/local-mcp-toolkit/register-toolkit.sh
```

- **Done 2026-11-16:** accepted at ~37 MiB zipped (the ~61 MiB package was
  refused first). Same tool names in two toolkits are fine: wxO prefixes
  them (`courts_analyst_syed_idb:find_cases`). Adding a tool to the agent
  from the new toolkit did not detach the old one; each old tool was
  removed separately.
- **413 / refused:** nothing changed. Shrink further before trying again. The
  next candidates are the party-name index (8-byte hashes; a delta-encoded
  format would change the output scanner, so it needs its own review) and
  the date columns.
- **Accepted:** check `orchestrate toolkits list` shows both toolkits with 17
  tools each. If wxO refuses duplicate tool names across toolkits, use 2b.

Then, on the **draft** agent in the UI: remove the 8 tools from
`courts_analyst_syed`. Add the same 8 plus the 4 case tools from
`courts_analyst_syed_idb` (Tools → Add Tool → Local instance → search the
toolkit name). Run the eval (step 3) before deploying a new version.

**Roll back 2a:** on the draft agent, remove the `courts_analyst_syed_idb` tools
and re-add the 8 from `courts_analyst_syed`. Then run `pre.sh v8` /
`agent_check.py --tools 8`. Removing the extra toolkit afterwards is a wxO
delete (owner's OK first) and isn't needed for the rollback.

## 2b. Replace the existing toolkit

Only after the upload size is proven (2a, or a throwaway name). Replacing
removes the toolkit first: every agent loses its tools until they are
re-attached. The **Live** version may lose them too: check Orchestrate Chat
right after.

```bash
TOOLKIT_NAME=courts_analyst_syed REPLACE_EXISTING=1 INCLUDE_IDB=1 \
  bash deploy/ibm/local-mcp-toolkit/register-toolkit.sh
```

Without `REPLACE_EXISTING=1` the script stops with "Nothing changed". When
replacing, it also stops before removing anything if the package is over
`MAX_STAGE_MB` (default 100; the slim package is ~83 MB on disk).

Re-attach in the UI: Tools → Add Tool → Local instance → search
`courts_analyst_syed`. Add the 8 tools, plus the 4 case tools if wanted.

**Roll back 2b:** re-register without the IDB from the commit the evaluated
toolkit came from:

```bash
git worktree add ../courts-rollback 159f529
cd ../courts-rollback
set -a; source ../courts-mcp/deploy/ibm/local-mcp-toolkit/.env; set +a
DUCKDB_PATH=../courts-mcp/data/build/courts.duckdb \
  bash deploy/ibm/local-mcp-toolkit/register-toolkit.sh   # INCLUDE_IDB unset
cd ../courts-mcp && git worktree remove ../courts-rollback
```

The script at 159f529 has no `REPLACE_EXISTING` guard: it removes and
re-imports. Then re-attach the 8 tools (list above) and check with
`pre.sh v8` / `agent_check.py --tools 8`. If Live lost its tools, redeploying
needs the owner's OK.

## 3. Evaluate the new setup

Dev split only. Held-out test2 was scored once (80.0%) and is not re-run.

```bash
TOOLS=12 AGENT_TOOLS=wxo-idb eval/wxo/run_eval.sh dev
```

`wxo-idb` scores 125 dev items: the 117 of the `wxo` preset plus 8 that need a
case tool. Compare on the 117 shared items against dev 88.3% (re-scored).
Report the 8 separately, and count `connection refused` tool-runtime failures
apart from wrong answers. The agent's v8 instructions don't mention the case
tools; keep v8 unless the transcripts show it needs a rule.
