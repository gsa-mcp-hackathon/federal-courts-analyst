# ADR 0013: A sandboxed request desk; the official data stays read-only

- **Status:** Proposed (implemented in Phase 9b; awaiting team agreement,
  the GSA track question and the Third Branch Solutions check below)
- **Date:** 2026-10-21

## Context

Until now the server is read-only by design: the concept lists "read-only,
sandboxed, public data only" as a guardrail, and ADR 0008 gives the core one
`READ_ONLY` connection so no code path can write to the catalog or the IDB.

Three things argue for adding writes on top:

- **The hackathon rewards them.** Its tracks are Dataset Access, Service Read
  and Service Write; a write use case submits a form, creates a case record or
  files a request, in a sandbox so nothing real is affected.
- **The service exists, by hand.** uscourts.gov's Contact Us form takes
  "requests for publications or statistics"; AO staff answer congressional
  inquiries by email, phone and briefings; the FJC takes IDB questions at
  IDBonline@fjc.gov. FOIA doesn't apply to the judiciary (reaffirmed by
  D.D.C. in December 2025), so there's no formal public route for an
  explanation.
- **Our data has a question only the AO can answer.** 1,340 published
  figures were revised between editions, and nothing published explains the
  weighted-filings revision (FY2020: 554 → 322). `revisions.py` labels our
  explanation "Unconfirmed: needs AO confirmation", and issue #8 is open for
  exactly that.

How the desk works for users: [docs/desk.md](../desk.md).

## Decision

1. **The official data stays read-only.** `core/db.py` and its tests are
   unchanged. The desk writes to its own store, a SQLite file at
   `desk_store_path` (never under `data/build`, which is mounted read-only;
   `/tmp` or a mounted volume in the container). SQLite because the desk is
   row-level, transactional writing (DuckDB is the analytical engine and
   holds a single-writer lock per file), and it ships with Python: no new
   dependency. Unset, the store is in memory, so tests and a fresh demo
   start empty.
2. **Asking stays read-only.** A question writes nothing, as today. A write
   happens only when the user picks one of three options under an answer:
   *Ask the statistics office why this changed*, *Save a verified copy*, or
   *Notify me if these numbers change*. The agent is never offered a desk
   tool (`agent/mcp_clients.py` filters them out), so a model can't write,
   and a model that names one gets "Unknown tool". The web app's buttons
   call the REST routes directly, and the web app (not the model) looks up
   library matches.
3. **One pure module, the usual adapters.** `core/desk/` holds the records,
   status rules, roles, the verification gate and the audit log, with no
   MCP or HTTP imports (ADR 0002). Every entry point returns a `Result` and
   is `@guarded` (ADR 0010), so the registry tests cover the desk too. MCP
   tools are thin files in `tools/`; REST routes in `api/routes/desk.py`
   return the same envelopes.
4. **Five write tools and one read tool.**

   | Tool | Role | Writes |
   | --- | --- | --- |
   | `open_request` | public | A request: the option chosen, the question, the asker's role, the court, years and measure it resolves to |
   | `save_verified_answer` | public | The answer and one citation per number, only if the gate passes |
   | `file_revision_inquiry` | public | An inquiry about one revision, or the asker added to an existing one |
   | `record_official_response` | staff | The office's reply, and an update to everyone waiting on it |
   | `publish_answer` | staff | The approved answer in the public library |
   | `find_published_answers` | read | Nothing |

   Write tools carry `readOnlyHint: false`, `destructiveHint: false`,
   `idempotentHint: true` and take an idempotency key: a retried call
   returns the first result instead of a second record. Each write is
   confirmed first, by MCP elicitation where the client supports it and
   otherwise in two steps (`confirm=false` returns a preview of what would be
   written; `confirm=true` writes it). For `keep_answer` the second call must
   carry the preview's `preview_id` (see *As built*). No generic tools such as
   `update_status`: statuses change only inside these tools.
5. **The verification gate.** An answer is saved only if:
   - every number in the text is a cited value (measure, court, fiscal year,
     edition, value), a published threshold, a difference or percentage
     change between backed numbers, or a number the server's own read tools
     produce when it re-runs the answer's tool calls (names and arguments
     come from the request; values never do). Fiscal years, table codes,
     docket numbers, dates, links and code are skipped;
   - every cited value is exactly what that edition printed, and an edition
     written right after a number is the one it's cited from;
   - the citations for each measure are consistent in the sense of
     `guardrails.vintage` (one series, no edition contradicting another
     point), unless a sentence labels a value as first-published or revised;
   - the PII scanner and the neutral-wording check pass.

   The re-run exists because the agent cites only some figures as citation
   events; the rest of a real answer (points per district, case counts)
   comes from tool outputs. MCP and REST share the re-run.

   A refusal names each offending number and what to use instead ("554 is
   JB-2020; the other figures are JFF-2025, which prints 322"). The number
   finder in `evaluation/scoring/figures.py` (`figures_in_text`) moves into
   `core/` so the gate and the scorer read numbers the same way; the scorer
   imports it from there. The 430 and 600 thresholds are cited to
   `core/data/judgeships.yaml`.
6. **Inquiries are about a revision, never free text.** An inquiry names a
   revision the catalog holds (measure, court, fiscal year, from-edition,
   to-edition) and is allowed only when `revision_notes` has no official
   explanation for it. One inquiry exists per revision; later askers are
   attached to it, so the office's workload is capped by the number of
   unexplained revisions, not by users. Table figures route to the AO
   Statistics Division (every revision the catalog tracks is a published
   table figure; `route_for` sends IDB-derived figures to IDBonline@fjc.gov
   when such inquiries are added). In the sandbox nothing is sent: the record says "would go to … (sandbox: not
   sent)".
7. **Two roles.** Public users and the statistics office. In the sandbox the
   office is played by a teammate and labelled "simulated" everywhere it
   appears. Staff routes and the staff screen require a separate
   `desk_staff_token`. The two staff tools are registered on MCP only when
   `desk_staff_mode` is on, so a public MCP client never sees them. Public
   users sign in with demo accounts (a display name and a role from a fixed
   list); no real identity is collected.
8. **A response flows back into the read tools.** `revision_notes` gains a
   third basis, `office_response`, read from the desk store. While the store
   is the sandbox, its text says "Response entered by the simulated
   statistics office (sandbox)", and the `inferred_not_official` warning
   stays. Simulated responses are never presented as official.
9. **Requests stay current.** On a new catalog build (the build hash
   changes), a check compares every saved citation with the catalog: library
   answers that cite a revised figure are flagged `needs_reverification`,
   and askers who chose *Notify me* get an update. It runs at startup and as
   `make desk-check`. Updates are in-app only (a My requests inbox); the
   sandbox sends no email.
10. **Every write is audited.** Each write appends an `audit_event` (who,
    which tool, which record, before and after status). The table is
    append-only, so the demo can replay a request end to end.

## Consequences

- The read-only guarantee narrows from "the server can't write" to "the
  server can't write the official data". A test asserts the catalog and IDB
  connections stay `READ_ONLY` and that only `core/desk/` opens the desk
  store.
- The concept's "read-only" guardrail and the README's track line need
  updating once GSA answers the track question.
- SQLite with WAL is fine for one worker and a demo; several replicas would
  need a shared store (the same limit as pending clarifications, #39).
- Stored question text goes through the PII scanner before it's saved;
  `make desk-reset` empties the sandbox.
- Issue #8 gets a working path: the 554 → 322 inquiry is the demo's main
  thread. Issue #45 (shareable answer links) is covered by *Save a verified
  copy*.
- The office's side (`record_official_response`, `publish_answer`) models a
  review process nobody outside the AO can see. It stays an assumption until
  Third Branch Solutions confirms how the AO handles statistics questions
  today.

## As built (Phase 9b)

- **The desk is complete over MCP.** Any MCP client can do what the web app
  does: `keep_answer` (one call: check, then request, answer and inquiry),
  `my_requests`, `check_inquiry_eligibility`, `find_published_answers`, the
  `desk://library` resource and the `keep_this_answer` prompt, plus the
  three step-by-step tools above and, in staff mode, `inquiry_queue`. The
  tool re-run lives in `tools/_rerun.py`, shared by MCP and REST. Demo
  account names resolve to the same account in every client
  (`core/desk/accounts.py`), so one person has one inbox.

- Eligibility is decided by the server for each cited figure, not by the
  citation's `revised` flag: figures cited from `explain_change` carry
  `revised: false` (issue #37), which hid the FY2020 inquiry in testing.
- Write-safety suite: 22 cases, all passing
  ([eval/results/write-safety.md](../../eval/results/write-safety.md)).
- FastMCP 4's server-wide cache hint (ADR 0001) also covers desk tools. A
  client honouring it could reuse a library search for up to an hour; write
  results are keyed by idempotency key, so a reused write result is the
  same as a replay.

- **`keep_answer` checks the preview (2026-11-15).** In watsonx
  Orchestrate transcripts, after a save came back `written: false` and the
  user restated the text, the agent called `keep_answer` with
  `confirm=true` again without a new "Shall I go ahead?" (3 of 10 desk
  transcripts); instruction changes didn't stop it. Now a `confirm=false`
  call returns a `preview_id` bound to a SHA-256 digest of the answer text
  (ignoring whitespace and typographic dashes and quotes, which models
  swap when they re-emit an answer), option, asker (account and role), citations
  (sorted) and inquiry target, kept in the desk store's `preview` table so
  it survives a stdio server restarted between calls. A `confirm=true`
  call without a matching id returns `written: false` with a message
  telling the agent to show a preview and ask "Shall I go ahead?" first.
  Each id is used up by its first `confirm=true` call, whatever the
  outcome, so a retry after a refused save needs a new preview. Two
  exceptions: a retry with an `idempotency_key` that already wrote replays
  the first result, and a client that confirms by elicitation needs no id
  (the client asked the user itself). The id proves a preview call was
  made for exactly what is written; it can't prove the user saw it, so the
  agent instructions' preview rule and the transcript checker
  (`courts-eval preview-check`) stay. `core/desk/previews.py`,
  `tests/test_keep_answer_preview.py`.

- **Re-run numbers join the consistency check (2026-11-15).** A wxO desk
  run saved "554 in FY2020 and 318 in FY2021" as verified (Request #1008):
  554 was cited from JB-2020, and 318 was backed only by re-running
  `get_official_figure`, whose output lists every edition's value, so rule 3
  never saw it. Now a re-run number whose sentence names a fiscal year, and
  which a cited measure's chain prints for that year, counts as cited from
  an edition that prints it: the one written beside it, else one the answer
  already cites, else one of the same series, else the latest. The history
  test is re-run with these numbers, so "554 (JB-2020) -> 322 (JFF-2023,
  current)" stays history. A re-run number with no fiscal year in its
  sentence, or for a measure the answer doesn't cite, is still not placed.
- **`ask_office` is checked before the user is asked (2026-11-15).**
  `keep_answer` runs `check_option` with `check_text`, before a preview or an
  elicitation: the inquiry must be given, cited by the answer, and eligible.
  In wxO runs the agent left out `inquiry`, the user said yes, and only the
  confirming call failed. The message now names the missing argument.

## Alternatives considered

- **Write into the catalog or a DuckDB file like the cohort store.** The
  cohort store holds deterministic, recreatable handles; desk records are
  the only copy of what someone asked and what the office said, and need
  transactions and row-level updates.
- **Write on every question.** Rejected: it stores what every staffer asks,
  fills the queue with look-ups, and gives users no reason to trust it.
- **Let the agent file inquiries or approve answers.** Rejected: a person
  chooses every public write, and only staff approve.
- **Send real email to the AO or FJC.** Rejected for the sandbox; the
  routing is shown, not executed.
- **Generic ticketing tools.** Rejected: the judges look for goal-oriented
  tools, and each desk tool exists because of something particular to this
  data (editions, revisions, unexplained changes).
