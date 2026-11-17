#!/usr/bin/env bash
# Register this MCP server as a LOCAL MCP toolkit in watsonx Orchestrate.
#
# A local MCP toolkit ships this server's code to Orchestrate, which installs it
# (via requirements.txt at package_root) and runs `python server.py` over stdio
# INSIDE the Orchestrate runtime — no HTTP endpoint, no Code Engine, no container.
#
# Prerequisites:
#   - Python 3.11-3.14
#   - ADK installed:  pip install --upgrade ibm-watsonx-orchestrate
#   - Config:         cp .env.example .env && edit
#
# Usage:
#   set -a; source deploy/ibm/local-mcp-toolkit/.env; set +a
#   #   export WXO_API_KEY="<your key>"     # else you'll be prompted (hidden)
#   bash deploy/ibm/local-mcp-toolkit/register-toolkit.sh
#
# Options (environment variables):
#   INCLUDE_IDB=1        also ship the civil IDB, so the case-level tools work
#                        (find_cases, analyze_cohort, sample_dockets, reconcile).
#   IDB_DUCKDB_PATH      which IDB to ship; default data/build/slim/idb.duckdb,
#                        the slim copy from `make data-idb-slim` (~66 MiB; the
#                        full build is ~440 MB and was refused with a 413).
#   REPLACE_EXISTING=1   replace a toolkit that already has TOOLKIT_NAME. Without
#                        it the script stops and changes nothing: replacing
#                        removes the old toolkit first, which takes its tools off
#                        every agent (re-attach them in the UI afterwards).
#   MAX_STAGE_MB         size cap (default 100) checked only when replacing, so
#                        a refused upload can't leave the name empty. Try a new
#                        size under a throwaway TOOLKIT_NAME first; a refusal
#                        there breaks nothing.
set -euo pipefail

# --- Validate config ----------------------------------------------------------
: "${WXO_ENV_NAME:?set WXO_ENV_NAME (source deploy/ibm/local-mcp-toolkit/.env)}"
: "${WXO_INSTANCE_URL:?set WXO_INSTANCE_URL}"
: "${TOOLKIT_NAME:?set TOOLKIT_NAME}"

# This script lives in the kit dir; toolkit.yaml sits next to it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# repo root is three levels up: deploy/ibm/local-mcp-toolkit -> repo root
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
STAGE_DIR="${SCRIPT_DIR}/_stage"
TOOLKIT_YAML="${SCRIPT_DIR}/_toolkit.generated.yaml"

# The package to ship. If you renamed `courts_analyst`, set PACKAGE_NAME to match
# (or export it before running).
PACKAGE_NAME="${PACKAGE_NAME:-courts_analyst}"

echo "=== Target ==="
echo "  env name:      ${WXO_ENV_NAME}"
echo "  instance URL:  ${WXO_INSTANCE_URL}"
echo "  toolkit name:  ${TOOLKIT_NAME}"
echo "  package:       ${PACKAGE_NAME}"
echo ""

# --- Confirm the ADK is installed ---------------------------------------------
if ! command -v orchestrate >/dev/null 2>&1; then
  echo "FATAL: 'orchestrate' not found. Install the ADK:" >&2
  echo "       pip install --upgrade ibm-watsonx-orchestrate" >&2
  exit 1
fi

# --- Obtain the API key (never written to disk) -------------------------------
API_KEY="${WXO_API_KEY:-}"
if [[ -z "${API_KEY}" ]]; then
  echo "=== watsonx Orchestrate API key ==="
  read -r -s -p "  API key (input hidden): " API_KEY
  echo ""
  if [[ -z "${API_KEY}" ]]; then
    echo "FATAL: no API key provided." >&2
    exit 1
  fi
fi

# --- Point the ADK at the instance and activate it ----------------------------
echo "=== Configuring ADK environment '${WXO_ENV_NAME}' ==="
if grep -qw -- "${WXO_ENV_NAME}" <<<"$(COLUMNS=500 orchestrate env list 2>/dev/null)"; then
  echo "  env exists — reusing."
else
  orchestrate env add --name "${WXO_ENV_NAME}" --url "${WXO_INSTANCE_URL}" --type ibm_iam
fi
orchestrate env activate "${WXO_ENV_NAME}" --api-key "${API_KEY}"
orchestrate env list

# --- Does a toolkit with this name exist already? -----------------------------
# The list is a table drawn to the terminal width. Without a terminal (nohup,
# CI) it is 80 columns wide and the name column wraps, so grep would miss the
# toolkit; COLUMNS=500 keeps each row on one line.
TOOLKIT_EXISTS=0
if grep -qw -- "${TOOLKIT_NAME}" <<<"$(COLUMNS=500 orchestrate toolkits list 2>/dev/null)"; then
  TOOLKIT_EXISTS=1
  if [[ "${REPLACE_EXISTING:-0}" != "1" ]]; then
    echo "FATAL: toolkit '${TOOLKIT_NAME}' already exists. Nothing changed." >&2
    echo "       Replacing it removes it first and takes its tools off every" >&2
    echo "       agent. Set REPLACE_EXISTING=1 to replace it (see ROLLBACK.md)," >&2
    echo "       or pick a new TOOLKIT_NAME." >&2
    exit 1
  fi
  echo "  toolkit '${TOOLKIT_NAME}' exists; REPLACE_EXISTING=1, will replace it."
else
  echo "  toolkit '${TOOLKIT_NAME}' is new."
fi

# --- Build a minimal, self-contained staging package_root --------------------
# Uploading the whole repo hits a 413 (virtualenvs are large) and can fail the
# server-side install. We stage ONLY what the server needs, FLATTENED out of the
# src/ layout: `${PACKAGE_NAME}/` sits directly at package_root next to
# server.py, so it's importable with no install step.
echo "=== Staging minimal package_root at ${STAGE_DIR} ==="
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"
cp -R "${REPO_ROOT}/src/${PACKAGE_NAME}" "${STAGE_DIR}/${PACKAGE_NAME}"
cp "${SCRIPT_DIR}/server.py" "${STAGE_DIR}/server.py"
cp "${SCRIPT_DIR}/requirements.txt" "${STAGE_DIR}/requirements.txt"
# Ship the official tables catalog (~7 MB): without it every tool answers
# "data not built".
CATALOG="${DUCKDB_PATH:-${REPO_ROOT}/data/build/courts.duckdb}"
if [[ ! -f "${CATALOG}" ]]; then
  echo "FATAL: no catalog at ${CATALOG}. Build it first:" >&2
  echo "       uv run python -m courts_analyst.pipeline.tables all" >&2
  exit 1
fi
mkdir -p "${STAGE_DIR}/data"
cp "${CATALOG}" "${STAGE_DIR}/data/courts.duckdb"
# INCLUDE_IDB=1 ships the civil IDB too, so the case-level tools (find_cases,
# analyze_cohort, sample_dockets, reconcile) work. It has no party names; the
# hashed name index next to it lets the output scanner block any name that
# slips through. data/private/ (the party names) is never shipped.
# The default is the slim copy (`make data-idb-slim`, ~66 MiB): every record,
# minus the raw table and the columns the server never reads, stored compactly,
# with identical tool answers (tests/test_idb_slim.py). watsonx Orchestrate
# SaaS refused the full build (~440 MB) and a first slim copy (~61 MiB zipped)
# with a 413. Without INCLUDE_IDB=1 those tools say
# case data isn't loaded.
IDB="${IDB_DUCKDB_PATH:-${REPO_ROOT}/data/build/slim/idb.duckdb}"
if [[ "${INCLUDE_IDB:-0}" == "1" ]]; then
  if [[ ! -f "${IDB}" ]]; then
    echo "FATAL: INCLUDE_IDB=1 but no IDB at ${IDB}. Nothing changed." >&2
    echo "       Build it: make data-idb && make data-idb-slim" >&2
    rm -rf "${STAGE_DIR}"
    exit 1
  fi
  PII_INDEX="$(dirname "${IDB}")/pii_index.bin"
  if [[ ! -f "${PII_INDEX}" ]]; then
    echo "FATAL: no ${PII_INDEX}; the output scanner needs it to block party" >&2
    echo "       names. Run 'make data-pii-index' (and 'make data-idb-slim')." >&2
    echo "       Nothing changed." >&2
    rm -rf "${STAGE_DIR}"
    exit 1
  fi
  cp "${IDB}" "${STAGE_DIR}/data/idb.duckdb"
  cp "${PII_INDEX}" "${STAGE_DIR}/data/pii_index.bin"
  echo "  including the civil IDB ${IDB} ($(du -sh "${IDB}" | cut -f1))"
else
  echo "  civil IDB not included (INCLUDE_IDB=1 to ship it); case-level tools"
  echo "  will say case data isn't loaded."
fi
# Drop caches that may have been copied from src/.
find "${STAGE_DIR}" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
STAGE_SIZE="$(du -sh "${STAGE_DIR}" | cut -f1)"
echo "  staged package_root size: ${STAGE_SIZE}"
# When replacing, stop before touching the existing toolkit if the upload may be
# too large to be accepted: the import below removes the old toolkit first
# (which also takes its tools off every agent), so a refused upload would leave
# nothing behind. Refused with a 413: 454 MB, and 137 MB (~61 MiB zipped);
# ~10 MB is accepted. The ADK uploads a deflated zip. A new name
# has nothing to lose, so the cap doesn't apply: that's how to test a size.
STAGE_MB="$(du -sm "${STAGE_DIR}" | cut -f1)"
if (( TOOLKIT_EXISTS == 1 && STAGE_MB > ${MAX_STAGE_MB:-100} )); then
  echo "FATAL: staged package is ${STAGE_MB} MB, over MAX_STAGE_MB=${MAX_STAGE_MB:-100}." >&2
  echo "       watsonx Orchestrate refuses large uploads (413). Nothing was changed." >&2
  echo "       Test the size under a throwaway TOOLKIT_NAME first, then raise" >&2
  echo "       MAX_STAGE_MB; or leave out the IDB (INCLUDE_IDB=0)." >&2
  rm -rf "${STAGE_DIR}"
  exit 1
fi

# --- Generate the toolkit spec pointing at the staging dir --------------------
# The toolkit is registered under TOOLKIT_NAME (several participants share one
# instance, so names must be unique), not the template's placeholder name.
sed -E -e "s#^package_root:.*#package_root: ${STAGE_DIR}#" \
  -e "s#^name:.*#name: ${TOOLKIT_NAME}#" \
  "${SCRIPT_DIR}/toolkit.yaml" > "${TOOLKIT_YAML}"

# --- Import (or re-import) the local MCP toolkit ------------------------------
echo "=== Importing local MCP toolkit '${TOOLKIT_NAME}' ==="
if (( TOOLKIT_EXISTS == 1 )); then
  echo "  removing the existing toolkit before re-import. Agents lose these tools;"
  echo "  re-add them in the UI (Tools → Add Tool → Local instance) afterwards."
  orchestrate toolkits remove --name "${TOOLKIT_NAME}"
fi

orchestrate toolkits import -f "${TOOLKIT_YAML}"

# --- Clean up generated artifacts --------------------------------------------
rm -rf "${STAGE_DIR}" "${TOOLKIT_YAML}"

echo ""
echo "=== Registered ==="
orchestrate toolkits list
echo ""
echo "Next: build/edit an agent in the Orchestrate UI, add the '${TOOLKIT_NAME}'"
echo "tools, and chat-test a question (see README Part 3)."
