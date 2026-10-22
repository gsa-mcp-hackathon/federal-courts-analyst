# The request desk (sandbox)

A write workflow on top of the analyst ([ADR 0013](adr/0013-request-desk.md),
[Phase 9b](../plan/phase-09b-request-desk.md)). Asking a question writes
nothing. When an answer matters, the user picks one of three options under
it, and only then is anything stored:

| Option | Shown when | What the user gets |
| --- | --- | --- |
| **Ask the statistics office why this changed** | The answer cites a figure revised between editions that no published note explains (the server decides, per cited figure) | The answer saved as verified; one inquiry about that revision (shared with everyone who asks it); an update in My requests when the office responds |
| **Save a verified copy** | Any answer with cited figures | A stamped answer to cite: "Verified: every number checked against official data (…). Request #1002." |
| **Notify me if these numbers change** | Any answer with cited figures | An update when a newer edition revises a figure the answer quotes |

The statistics office's side (responding to inquiries, approving answers
into the public library) is **simulated**: a teammate plays it on the staff
screen. Nothing is ever sent to the AO or the FJC; routing is shown, not
executed ("would go to AO Statistics Division … Sandbox: recorded here, not
sent").

## The official data stays read-only

The catalog and the IDB are attached `READ_ONLY` as before (ADR 0008). Desk
records live in a separate SQLite file at `DESK_STORE_PATH` (in memory when
unset). `tests/test_desk_read_only_boundary.py` checks that only
`core/desk/store.py` opens a writable SQLite connection and that the catalog
still refuses writes.

## The verification gate

`core/desk/gate.py` decides whether an answer may be saved. Every number in
the text must be one of:

1. **A cited official figure.** Each citation (measure, court, fiscal year,
   edition, value) must match what that edition printed.
2. **A number the server's own read tools produce.** The web app sends the
   answer's tool calls (names and arguments only); the server re-runs the
   read-only ones in process (`get_official_figure`, `explain_change`,
   `compare_courts`, `find_cases`, `analyze_cohort`, `reconcile`,
   `judgeship_context`) and accepts numbers their outputs hold. No value is
   ever taken from the request. MCP clients pass `tool_calls` to
   `keep_answer` or `save_verified_answer` and get the same re-run
   (`tools/_rerun.py`, shared with the REST routes).
3. **A published threshold** (430, 600), or a **difference or percentage
   change** between numbers the answer already backs.

Fiscal years, table codes, docket numbers, dates, links and inline code are
not statistics and are skipped. On top of that:

- **Editions stay consistent.** One measure's cited figures come from one
  series, and no edition used for one figure prints another differently
  (`guardrails.vintage`). A value quoted as history in a sentence that says
  so ("first published as 554") is allowed.
- **Labels match.** An edition written right after a number ("322
  (JFF-2024)") must be the edition it's cited from.
- **No advocacy**, no party names (the IDB scanner), no judge-level
  requests.

A refusal lists each number with what to write instead, for example:
"554 comes from JB-2020, but the other … figures come from JFF-2024. Fix: Use
322 (JFF-2024), or say that 554 was the first-published figure."

Known limit: a number the server's tools can't reproduce is refused even if
it's right. On the committed test fixtures, the IDB is a sample, so case
counts from the full database (201,017 directly filed MDL cases) are refused
there; on the full build they match.

## Records and statuses

Tables: `request`, `answer` (versioned), `citation`, `inquiry` (unique per
revision), `inquiry_request`, `response`, `library_entry`, `request_update`
(the inbox), `idempotency`, `audit_event` (append-only, enforced by
triggers).

```
received → verified → waiting_for_office → office_responded → published   (Ask the statistics office)
received → verified (→ published)                                          (Save a verified copy)
received → watching (→ published)                                          (Notify me)
```

Anything else is `invalid_transition` (409).

## Who can do what

| Action | Public (demo account) | Statistics office (staff token) | The agent |
| --- | --- | --- | --- |
| Ask questions | yes | yes | yes |
| Keep an answer, see My requests (web or any MCP client) | yes | n/a | **never** (the web app's agent is not offered desk tools) |
| See the inquiry queue, respond, publish, audit log | no | yes | never |
| Search the library | yes | yes | no (the web app shows matches) |

Public users sign in with invented demo accounts; no real identity is
collected. Requests are private to their asker. An MCP client passes the
account's name as `asker_name` ("Priya"), so a request kept from Claude
Desktop is in the same My requests as one kept in the web app. (MCP callers
aren't authenticated: in the sandbox, a name is a claim, not a login.)

## Using it

| Where | How |
| --- | --- |
| Web | Options under each answer; **My requests**, **Library**; **Statistics office (simulated)** in the footer (asks for `DESK_STAFF_TOKEN`) |
| REST | `POST /api/desk/requests` (an option), `GET /api/desk/requests[/{id}]`, `POST /api/desk/requests/{id}/read`, `GET /api/desk/library`, `GET /api/desk/eligibility`, `GET /api/desk/accounts`; staff: `GET /api/desk/staff/inquiries`, `GET /api/desk/staff/requests`, `POST /api/desk/staff/inquiries/{id}/response`, `POST /api/desk/staff/requests/{id}/publish`, `GET /api/desk/staff/audit`, `POST /api/desk/staff/check-staleness` |
| MCP (any client) | `keep_answer` (one call: check, then save, plus the inquiry for *Ask the statistics office*), `my_requests`, `check_inquiry_eligibility`, `find_published_answers`; the same steps one at a time with `open_request`, `save_verified_answer`, `file_revision_inquiry`; with `DESK_STAFF_MODE=true` also `inquiry_queue`, `record_official_response`, `publish_answer`. Resource `desk://library`; prompt `keep_this_answer`. Writes are confirmed by elicitation, or return a preview until called with `confirm=true`. `keep_answer` and `save_verified_answer` take `tool_calls` and re-run them like the web app does |
| Make | `make desk-seed` (the demo's opening state: one inquiry already waiting), `make desk-check` (flag answers citing figures a newer edition revised; also runs at HTTP startup), `make desk-reset`, `make eval-write-safety` |

Settings: `DESK_STORE_PATH`, `DESK_STAFF_TOKEN`, `DESK_STAFF_MODE` (see
`.env.example`). In the container the store goes under `/tmp` (the root
filesystem is read-only): `make docker-run` sets
`DESK_STORE_PATH=/tmp/desk/desk.sqlite`.

## Evaluation

`make eval-write-safety` runs 19 attempts the desk must refuse or allow
(mixed editions, uncited and invented numbers, wrong edition labels,
advocacy, the agent approving its own answer, a public user responding as
the office, inquiries about explained or unrevised figures, duplicate
inquiries, judge and party requests, retries, out-of-order publishing,
someone else's request, writes without confirmation). Results:
[eval/results/write-safety.md](../eval/results/write-safety.md).
