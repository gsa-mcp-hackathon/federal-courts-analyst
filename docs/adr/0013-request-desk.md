# ADR 0013: A sandboxed request desk; the official data stays read-only

- **Status:** Proposed (awaiting team agreement, the GSA track question and
  the Third Branch Solutions check below)
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

The proposal page for the team:
<https://claude.ai/artifact/CewQdRmQFWWbYUVCVavbts>.

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
   *Notify me if these numbers change*. The agent never calls a write tool
   on its own initiative; the loop refuses write tools unless the turn came
   from one of those actions.
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
   written; `confirm=true` writes it). No generic tools such as
   `update_status`: statuses change only inside these tools.
5. **The verification gate.** `save_verified_answer` refuses unless:
   - every number in the text, other than fiscal years and table codes, is
     backed by a citation (measure, court, fiscal year, edition, value);
   - every cited value is exactly what that edition printed;
   - the citations for each measure are consistent in the sense of
     `guardrails.vintage` (one series, no edition contradicting another
     point), unless a sentence labels a value as first-published or revised;
   - the PII scanner and the neutral-wording check pass.

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
   Statistics Division and IDB-derived figures to IDBonline@fjc.gov. In the
   sandbox nothing is sent: the record says "would go to … (sandbox: not
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
