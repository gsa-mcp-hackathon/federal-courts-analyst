#!/usr/bin/env bash
# Reproduce the watsonx Orchestrate evaluation of the courts-analyst agent.
#
#   eval/wxo/run_eval.sh dev|heldout [INSTRUCTIONS_FILE]
#
# 1. checks the environment (never prints the key),
# 2. checks that the live agent runs INSTRUCTIONS_FILE (default v8.txt, the
#    final version) with the expected tools, and writes provenance,
# 3. runs Layer 2: courts-eval over the dev split or the test2 held-out split,
#    tools on the agent only, REPEATS runs per item, with that provenance,
# 4. checks the request-desk preview rule over the run records,
# 5. with DESK=1, runs the three Layer 1 desk tests (orchestrate evaluations) and
#    checks the preview rule over their transcripts.
#
# The held-out split is meant to be scored once per configuration: a second
# heldout run with the same instructions stops unless HELDOUT_AGAIN=1.
# Exit status: 0 when every step passed, 1 on a failed check or violation.
#
# Environment: WXO_INSTANCE_URL, WXO_API_KEY, WXO_AGENT_ID (required);
# WXO_ENV_NAME (orchestrate env, needed for the agent check and DESK=1);
# AGENT_NAME (the agent's internal name, needed for DESK=1);
# REPEATS (3), WORKERS (3), TOOLS (8), RESULTS_DIR (eval/results);
# AGENT_TOOLS (wxo): the --agent-tools preset; wxo-idb with TOOLS=12 for the
# agent with the case-level tools (toolkit shipped with INCLUDE_IDB=1);
# SKIP_AGENT_CHECK=1 to run without the orchestrate CLI (provenance is then
# the instruction file's hash only).
set -euo pipefail

usage() { echo "usage: $0 dev|heldout [instructions file]" >&2; exit 2; }
die() { echo "run_eval: $*" >&2; exit 1; }

kind=${1:-}
case "$kind" in
  dev) split=dev ;;
  heldout) split=test2 ;;
  *) usage ;;
esac
instr=${2:-eval/wxo/instructions/v8.txt}
[[ -f "$instr" ]] || die "no instruction file $instr"

: "${WXO_INSTANCE_URL:?set WXO_INSTANCE_URL}"
: "${WXO_AGENT_ID:?set WXO_AGENT_ID}"
[[ -n "${WXO_API_KEY:-}" ]] || die "WXO_API_KEY is not set (read -rs -p 'key: ' WXO_API_KEY; export WXO_API_KEY)"

REPEATS=${REPEATS:-3}
WORKERS=${WORKERS:-3}
TOOLS=${TOOLS:-8}
RESULTS_DIR=${RESULTS_DIR:-eval/results}
COURTS_EVAL=${COURTS_EVAL:-uv run courts-eval}
PYTHON=${PYTHON:-python3}
mkdir -p "$RESULTS_DIR"

sha=$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read().rstrip(b"\n")).hexdigest())' "$instr")
marker="$RESULTS_DIR/.heldout-${sha:0:16}"
if [[ $kind == heldout && -e "$marker" && "${HELDOUT_AGAIN:-}" != 1 ]]; then
  die "held-out split already scored with $instr ($(cat "$marker")); set HELDOUT_AGAIN=1 to run it again"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
prov="$work/provenance.json"

# --- 2. agent check ----------------------------------------------------------
if [[ "${SKIP_AGENT_CHECK:-}" == 1 ]]; then
  printf '{"agent_id": "%s", "instructions_file": "%s", "instructions_sha256": "%s", "agent_check": "skipped"}\n' \
    "$WXO_AGENT_ID" "$instr" "$sha" > "$prov"
else
  : "${WXO_ENV_NAME:?set WXO_ENV_NAME (or SKIP_AGENT_CHECK=1)}"
  orchestrate env activate "$WXO_ENV_NAME" --api-key "$WXO_API_KEY" > /dev/null 2>&1 \
    || die "orchestrate env activate $WXO_ENV_NAME failed"
  orchestrate agents list -v > "$work/agents.txt" 2>&1 || die "orchestrate agents list failed"
  "$PYTHON" eval/wxo/agent_check.py "$work/agents.txt" "$WXO_AGENT_ID" "$instr" \
    --tools "$TOOLS" --out "$prov" || die "the live agent doesn't match $instr"
fi

# --- 3. Layer 2 --------------------------------------------------------------
stamp="$work/stamp"
touch "$stamp"
$COURTS_EVAL run --answerer wxo --split "$split" --repeats "$REPEATS" \
  --agent-tools "${AGENT_TOOLS:-wxo}" --workers "$WORKERS" --results-dir "$RESULTS_DIR" \
  --provenance "$prov"
records=$(find "$RESULTS_DIR" -maxdepth 1 -name '*.jsonl' -newer "$stamp" | sort | tail -1)
[[ -n "$records" ]] || die "courts-eval wrote no run records to $RESULTS_DIR"
echo "run_eval: run records $records"
if [[ $kind == heldout ]]; then
  basename "$records" > "$marker"
fi

# --- 4. preview rule over the run --------------------------------------------
status=0
$COURTS_EVAL preview-check "$records" || status=1

# --- 5. Layer 1 desk tests ---------------------------------------------------
if [[ "${DESK:-}" == 1 ]]; then
  : "${AGENT_NAME:?set AGENT_NAME, the internal agent name, for DESK=1}"
  for t in l1desk l1desk2 l1desk3; do
    touch "$stamp"
    orchestrate evaluations evaluate -p "eval/wxo/tests/$t" -o eval/wxo/out
    out=$(find eval/wxo/out -mindepth 1 -maxdepth 1 -type d -newer "$stamp" | sort | tail -1)
    [[ -n "$out" ]] || die "no Layer 1 output for $t"
    $COURTS_EVAL preview-check "$out" || status=1
  done
fi

exit "$status"
