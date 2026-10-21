# Phase 9b: Request Desk (proposed)

**Status:** Proposed. Don't start the build until the three checks under
"Before we build" are answered.

**Goal:** a sandboxed write workflow on top of the analyst. When an answer
matters, a user can ask the statistics office why a figure changed, save a
verified copy, or ask to be notified if the numbers change. They follow each
one in a My requests inbox, and confirmed answers go into a public library
for the next person who asks. Asking a question stays read-only. Design:
[ADR 0013](../docs/adr/0013-request-desk.md). Proposal page for the team:
<https://claude.ai/artifact/CewQdRmQFWWbYUVCVavbts>.

**Judging impact:** Mission alignment (verified answers to Congress on a live
judgeship decision; a public route to official explanations where FOIA
doesn't reach), innovation (an edition-aware verification gate, confirmations
that flow back into the read tools, a library that flags its own stale
answers), technical quality (the same core/adapter and guardrail patterns for
writes), presentation ("request in, verified answer out", with two people on
screen).

**Runs:** after Phase 8, alongside Phase 9. It must land before Phase 10
freezes the held-out run (#71) and before Phase 11's demo script.

## Before we build

| Check | With | Changes |
| --- | --- | --- |
| Agree on the direction | Team | Whether this phase runs at all |
| Track: Dataset Access, Service Write, or either? | GSA | README, deck, concept doc |
| Who answers statistics questions at the AO today, and would they want inquiries like these? | Third Branch Solutions | How `record_official_response` and `publish_answer` are framed (real process or "what the AO could adopt") |

## Design

```
src/courts_analyst/
├── core/
│   ├── figures_text.py        # number + edition finder, moved from evaluation/scoring/figures.py
│   └── desk/
│       ├── __init__.py
│       ├── models.py          # Request, VerifiedAnswer, Citation, Inquiry, Response, LibraryEntry, Update, AuditEvent
│       ├── store.py           # DeskStore: SQLite (WAL), schema, transactions, idempotency keys
│       ├── status.py          # allowed status transitions
│       ├── gate.py            # the verification gate
│       ├── inquiries.py       # eligibility (revision exists, no official note), dedup, routing
│       ├── library.py         # publish, search, staleness check against a catalog build
│       └── roles.py           # public / staff
├── tools/
│   ├── open_request.py
│   ├── save_verified_answer.py
│   ├── file_revision_inquiry.py
│   ├── record_official_response.py   # registered only when desk_staff_mode is on
│   ├── publish_answer.py             # registered only when desk_staff_mode is on
│   └── find_published_answers.py
└── api/routes/desk.py         # /api/desk/... (public) and /api/desk/staff/... (staff token)
web/src/pages/
├── Requests.tsx               # My requests inbox
└── Staff.tsx                  # inquiry queue grouped by revision, response form, approve
```

### Records

| Table | Holds |
| --- | --- |
| `request` | id, option (`ask_office` / `verified_copy` / `notify`), asker id and role, question, resolved measure / court / fiscal years, status, created_at |
| `verified_answer` | request id, version, text, edition basis, gate result |
| `citation` | answer id, measure, court, fiscal year, edition, value, kind (`official_table` / `idb_derived` / `threshold`) |
| `inquiry` | the revision (measure, court, fiscal year, from-edition, to-edition, unique), route (AO / FJC), status |
| `inquiry_request` | which requests wait on which inquiry |
| `response` | inquiry id, outcome (`confirmed` / `corrected`), text, entered by |
| `library_entry` | answer id, published by, edition basis, `needs_reverification` |
| `update` | request id, kind, text, created_at, read |
| `audit_event` | append-only: actor, tool, record, status before and after, time |

### Statuses

`received → verified → (waiting_for_office → office_responded) → published`.
A *Notify me* request stays `watching` after `verified`. Any other transition
is a typed error.

### The three options

| Option | Shown when | Tools | Writes by the asker |
| --- | --- | --- | --- |
| Ask the statistics office why this changed | The answer cites a revised figure with no published explanation | `open_request`, `save_verified_answer`, `file_revision_inquiry`; later `record_official_response`, `publish_answer` by staff | 3 |
| Save a verified copy | Any answer | `open_request`, `save_verified_answer` | 2 |
| Notify me if these numbers change | Any answer | `open_request` (watch), `save_verified_answer` | 2 |
| (just asking) | | `find_published_answers` and the nine research tools | 0 |

### Agent and web

- The Ask page shows the three options under a finished answer. *Ask the
  statistics office* appears only when the turn cited a figure with
  `revision_status: revised` and no official note.
- A click sends `POST /api/desk/requests` with the turn's answer and its
  `citation` events, so the gate checks exactly what the user saw.
- The agent loop keeps write tools out of the model's tool list unless the
  turn starts from one of the options.
- Before research, the loop calls `find_published_answers`; a confirmed
  answer is shown first, marked with its edition and whether it's current.

## Tasks

- [ ] Move `figures_in_text` and the revision-wording pattern into `core/figures_text.py`; the scorer imports them (no change in eval scores)
- [ ] `core/desk/store.py`: schema, migrations by version number, WAL, idempotency keys, `desk_store_path` and `desk_staff_token` settings
- [ ] Status rules and typed errors
- [ ] The gate (`gate.py`), with refusal messages that name each number and the fix
- [ ] Inquiry eligibility, dedup and routing
- [ ] Library publish, search and the staleness check; `make desk-check`, `make desk-reset`
- [ ] `revision_notes` reads `office_response` notes from the desk store, labelled as simulated in the sandbox
- [ ] Six tool files with descriptions that pass `test_description_lint.py`; elicitation confirm with a two-step fallback
- [ ] REST routes (public and staff) with the same envelopes; rate limits on writes
- [ ] Agent loop: library check first; write tools only from an option
- [ ] Web: options under answers, My requests inbox, staff screen
- [ ] Seed script for the demo (two demo accounts, one staff account, the FY2020 storyline)
- [ ] Docs: README tools table and track line, `docs/desk.md` (records, statuses, gate rules), concept doc guardrail line
- [ ] File GitHub issues for anything left open; link #8 and #45

## Tests

| Test | Kind | Asserts |
| --- | --- | --- |
| `test_desk_read_only_boundary.py` | unit | Catalog and IDB connections are still `READ_ONLY`; only `core/desk/store.py` opens a writable connection |
| `test_desk_gate.py` | unit + property | Uncited number refused; wrong value refused; 554 beside JFF-2025 figures refused; 554 labelled "first published" allowed; thresholds pass with their citation; fiscal years and table codes ignored |
| `test_desk_status.py` | unit | Every allowed transition works; every other one is a typed error |
| `test_desk_inquiries.py` | unit | Only real, unexplained revisions; one inquiry per revision; second asker attached; AO vs FJC routing |
| `test_desk_roles.py` | unit + API | Staff tools refuse the public role; staff tools absent from `tools/list` without staff mode |
| `test_desk_idempotency.py` | unit | A retried write returns the first result; no duplicate rows |
| `test_desk_staleness.py` | integration | A new fixture build that revises a cited figure flags the library entry and creates an update for a *Notify me* request |
| `test_desk_audit.py` | unit | Every write appends one audit event; the table rejects updates and deletes |
| `test_desk_office_note.py` | unit | After a sandbox response, `get_official_figure` shows the note as simulated and keeps `inferred_not_official` |
| `test_desk_mcp.py` | MCP protocol | Annotations, schemas, elicitation confirm and the two-step fallback |
| `test_desk_api.py` | API | Envelopes match the tools; staff token required; rate limits |
| `test_agent_no_auto_writes.py` | agent (scripted) | A plain question makes zero writes; a scripted model that tries a write tool is refused |
| Playwright `desk.spec.ts` | e2e | The FY2020 storyline: ask, choose *Ask the statistics office*, staff responds, the asker sees the update, a second asker gets the library answer |
| Existing suites | regression | Eval scores unchanged after the `figures_in_text` move; guardrail registry covers `core/desk/` |

### Write-safety eval suite

About 15–20 items in the question bank (`suite: write_safety`), scored
deterministically: mixed-edition draft, uncited number, invented number,
wrong edition label, the agent trying to approve its own answer, an inquiry
about an explained revision, a duplicate inquiry, a judge-level request
submitted as a request, a party name in the question text, a public call to a
staff tool, a retried write. Each item checks the outcome (written or
refused) and the refusal reason.

## Exit criteria

- The FY2020 storyline runs end to end in local Docker and in Chrome:
  options under the answer, the gate refusing 554, the inquiry, the staff
  response, the inbox update, the library answer for a second user
- A plain question makes zero writes (agent test and an audit-log check)
- Write-safety suite: every item behaves as specified
- Coverage gates met; `core/desk/` at the same bar as the rest of `core/`
- ADR 0013 accepted, or revised after the team, GSA and Third Branch
  Solutions answers

## Risks

| Risk | Mitigation |
| --- | --- |
| Judges read the simulated office as a claim about the AO | "Simulated" label on every office record and screen; the deck says "what the AO could adopt" |
| Scope creep before the Phase 10 freeze | Cut order: *Notify me* and the staleness check first, then the library search in the agent loop; the gate and the inquiry are the core |
| The gate's number finder misses or over-matches | Shared with the scorer, which already has tests on real answers; gate refusals list numbers, so a wrong refusal is visible |
| A second worker or replica | One worker for the demo (same as #39) |

## Deviations

None yet.

## Evidence

To fill in when the phase runs.

## Open issues

To file when the phase starts. Related: [#8](https://github.com/syedaun-techsur/federal-courts-analyst/issues/8) (ask the AO about the 2023 revision), [#45](https://github.com/syedaun-techsur/federal-courts-analyst/issues/45) (shareable answer links), [#39](https://github.com/syedaun-techsur/federal-courts-analyst/issues/39) (single worker).
