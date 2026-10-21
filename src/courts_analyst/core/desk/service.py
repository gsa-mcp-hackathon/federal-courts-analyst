"""The request desk's entry points (ADR 0013).

Every function here returns a :class:`~courts_analyst.core.results.Result`
and is ``@guarded``, like the rest of the core, so MCP tools and REST routes
get the same envelopes and the same policies. Writes happen only through the
five write functions; each one runs in a single transaction, appends an
audit event, and accepts an idempotency key so a retried call returns the
first outcome instead of writing twice. With ``confirm=False`` a write
returns a preview and writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from courts_analyst.core.chain import later_revisions, load_chain, revision_status
from courts_analyst.core.courts import COURTS
from courts_analyst.core.db import Database
from courts_analyst.core.desk import status as status_rules
from courts_analyst.core.desk.errors import (
    DeskForbiddenError,
    DeskNotFoundError,
    InvalidTransitionError,
    NotEligibleError,
)
from courts_analyst.core.desk.gate import verify
from courts_analyst.core.desk.inquiries import eligibility as _eligibility
from courts_analyst.core.desk.inquiries import route_for
from courts_analyst.core.desk.models import (
    OPTION_LABELS,
    ROUTE_LABELS,
    Actor,
    AnswerView,
    AuditEventView,
    AuditLog,
    CheckedCitation,
    CitationIn,
    DeskOutcome,
    Eligibility,
    GateReport,
    InquiryQueue,
    InquiryView,
    LibraryEntryView,
    LibraryResults,
    Option,
    Outcome,
    RequestList,
    RequestView,
    ResponseView,
    StalenessReport,
    UpdateView,
)
from courts_analyst.core.desk.store import DeskStore, now
from courts_analyst.core.errors import DeclinedError
from courts_analyst.core.guardrails import guarded, party_names_in
from courts_analyst.core.guardrails.intent import screen
from courts_analyst.core.guardrails.policy import policy_decline
from courts_analyst.core.measures import get_measure
from courts_analyst.core.numbers import fmt
from courts_analyst.core.provenance import Period, Provenance, series_title
from courts_analyst.core.results import Caveat, Result

MAX_QUESTION = 2_000
MAX_ANSWER = 8_000
MAX_LIST = 50

DESK_PROVENANCE = Provenance(
    source="derived",
    definition="A request desk record in the sandbox: what someone asked and what "
    "the simulated statistics office answered. Not official data.",
    note="Sandbox (ADR 0013).",
)

SANDBOX_CAVEAT = Caveat(
    code="sandbox",
    severity="info",
    message="Request desk sandbox: nothing is sent to the AO or the FJC, and "
    "statistics-office responses are entered by a teammate playing that role.",
)

# ── views ────────────────────────────────────────────────────────────────────


def _court_name(code: str) -> str:
    c = COURTS.get(code)
    return (c.citation or c.name) if c else code


def _inquiry_view(store: DeskStore, inquiry_id: int) -> InquiryView:
    row = store.one("SELECT * FROM inquiry WHERE id = ?", [inquiry_id])
    if row is None:
        raise DeskNotFoundError(f"No inquiry #{inquiry_id}.", ["inquiry_queue"])
    waiting = store.one(
        "SELECT count(*) FROM inquiry_request WHERE inquiry_id = ?", [inquiry_id]
    )
    resp = store.one(
        "SELECT outcome, text, entered_by, created_at FROM response "
        "WHERE inquiry_id = ?",
        [inquiry_id],
    )
    return InquiryView(
        id=row["id"],
        measure=row["measure"],
        measure_label=get_measure(row["measure"]).label,
        court=row["court"],
        court_name=_court_name(row["court"]),
        fiscal_year=row["fiscal_year"],
        from_edition=row["from_edition"],
        from_value=row["from_value"],
        to_edition=row["to_edition"],
        to_value=row["to_value"],
        route=row["route"],
        route_label=ROUTE_LABELS[row["route"]],
        status=row["status"],
        waiting_requests=int(waiting[0]) if waiting else 0,
        created_at=row["created_at"],
        response=ResponseView(
            outcome=resp["outcome"],
            text=resp["text"],
            entered_by=resp["entered_by"],
            created_at=resp["created_at"],
        )
        if resp
        else None,
    )


def _citations(store: DeskStore, answer_id: int) -> list[CheckedCitation]:
    return [
        CheckedCitation.model_validate_json(r["record"])
        for r in store.rows(
            "SELECT record FROM citation WHERE answer_id = ? ORDER BY position",
            [answer_id],
        )
    ]


def _stamp(basis: Sequence[str], request_id: int) -> str:
    editions = ", ".join(basis) if basis else "no figures cited"
    return (
        f"Verified: every number checked against official data ({editions}). "
        f"Request #{request_id}. Sandbox."
    )


def _answer_view(store: DeskStore, request_id: int) -> tuple[AnswerView, int] | None:
    row = store.one(
        "SELECT * FROM answer WHERE request_id = ? ORDER BY version DESC LIMIT 1",
        [request_id],
    )
    if row is None:
        return None
    basis = [e for e in row["edition_basis"].split(",") if e]
    return (
        AnswerView(
            version=row["version"],
            text=row["text"],
            citations=_citations(store, row["id"]),
            edition_basis=basis,
            verified_at=row["verified_at"],
            stamp=_stamp(basis, request_id),
        ),
        int(row["id"]),
    )


def _request_view(store: DeskStore, request_id: int) -> RequestView:
    row = store.one("SELECT * FROM request WHERE id = ?", [request_id])
    if row is None:
        raise DeskNotFoundError(f"No request #{request_id}.", ["my_requests"])
    answer = _answer_view(store, request_id)
    inq = store.one(
        "SELECT inquiry_id FROM inquiry_request WHERE request_id = ?", [request_id]
    )
    updates = [
        UpdateView(
            id=u["id"],
            kind=u["kind"],
            text=u["text"],
            created_at=u["created_at"],
            read=bool(u["read"]),
        )
        for u in store.rows(
            "SELECT * FROM request_update WHERE request_id = ? ORDER BY id DESC",
            [request_id],
        )
    ]
    published = store.one(
        "SELECT 1 FROM library_entry WHERE request_id = ?", [request_id]
    )
    return RequestView(
        id=row["id"],
        option=row["option"],
        option_label=OPTION_LABELS[row["option"]],
        question=row["question"],
        asker_name=row["asker_name"],
        asker_role=row["asker_role"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        answer=answer[0] if answer else None,
        inquiry=_inquiry_view(store, inq[0]) if inq else None,
        updates=updates,
        unread=sum(not u.read for u in updates),
        needs_reverification=bool(row["needs_reverification"]),
        published=published is not None,
    )


def _provenance(db: Database, citations: Sequence[CitationIn]) -> list[Provenance]:
    out: list[Provenance] = []
    for c in citations:
        chain = load_chain(db, c.measure, c.court, c.fiscal_year)
        row = next((r for r in chain if r.edition == c.edition), None)
        if row is None:
            continue
        out.append(
            Provenance(
                source="official_table",
                table_code=row.table_code,
                series=series_title(row.edition),
                edition=row.edition,
                period=Period.for_end(c.fiscal_year, row.period_end),
                definition=get_measure(c.measure).definition,
                url=row.url,
                cell_ref=row.cell_ref,
                revision_status=revision_status(chain),
                first_published=chain[0].ref(),
                later_revisions=later_revisions(chain),
            )
        )
    return out


def _result(
    db: Database,
    data: Any,
    citations: Sequence[CitationIn] = (),
    warnings: list[Caveat] | None = None,
) -> Result[Any]:
    """An ``ok`` envelope. Provenance is the cited figures' (or the desk's own
    when nothing is cited); quoting one measure from both series is labelled."""
    prov = _provenance(db, citations) or [DESK_PROVENANCE]
    caveats = [SANDBOX_CAVEAT, *(warnings or [])]
    series: dict[str, set[str]] = {}
    for p in prov:
        if p.source == "official_table" and p.edition:
            series.setdefault(p.definition, set()).add(p.edition.split("-")[0])
    if any(len(s) > 1 for s in series.values()):
        caveats.append(
            Caveat(
                code="mixed_editions",
                severity="info",
                message="An earlier edition's value is quoted as history, next to "
                "the current figure; each is named with its edition.",
            )
        )
    model: Any = Result[type(data)]  # type: ignore[misc]
    result: Result[Any] = model(data=data, provenance=prov, warnings=caveats)
    return result


def _all_citations(views: Sequence[RequestView]) -> list[CitationIn]:
    return [c for v in views if v.answer for c in v.answer.citations]


# ── access rules ─────────────────────────────────────────────────────────────


def _own(store: DeskStore, actor: Actor, request_id: int) -> Any:
    row = store.one("SELECT * FROM request WHERE id = ?", [request_id])
    if row is None:
        raise DeskNotFoundError(f"No request #{request_id}.", ["my_requests"])
    if row["account_id"] != actor.account_id and not actor.staff:
        raise DeskForbiddenError(
            f"Request #{request_id} belongs to someone else.", ["my_requests"]
        )
    return row


def _staff(actor: Actor) -> None:
    if not actor.staff:
        raise DeskForbiddenError(
            "Only the statistics office (staff role) can do this.",
            ["sign in with the staff account on the staff screen"],
        )


def _screen_text(db: Database, text: str) -> None:
    """Refuse before anything is stored: judge-level and party-name requests,
    and text holding a party name from the IDB."""
    s = screen(text)
    if s.decline is not None:
        raise DeclinedError(s.decline.message, s.decline.reason, decline=s.decline)
    if party_names_in(db, text):
        d = policy_decline("pii")
        raise DeclinedError(d.message, d.reason, decline=d)


def _replay(
    store: DeskStore, actor: Actor, tool: str, key: str | None
) -> DeskOutcome | None:
    saved = store.remembered(actor.account_id, tool, key)
    if saved is None:
        return None
    outcome = DeskOutcome.model_validate_json(saved)
    outcome.message = "Already done with this idempotency key: " + outcome.message
    return outcome


def _clean(text: str, limit: int, what: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()
    if not text:
        raise NotEligibleError(f"The {what} is empty.")
    if len(text) > limit:
        raise NotEligibleError(f"The {what} is longer than {limit:,} characters.")
    return text


# ── reads ────────────────────────────────────────────────────────────────────


@guarded
def inquiry_eligibility(
    db: Database, measure: str, court: str, fiscal_year: int
) -> Result[Eligibility]:
    """Whether a figure's revision can be sent to the statistics office."""
    e = _eligibility(db, measure, court, fiscal_year)
    return _result(db, e)


@guarded
def my_requests(db: Database, store: DeskStore, actor: Actor) -> Result[RequestList]:
    """The caller's requests, newest first, with unread updates."""
    ids = [
        r[0]
        for r in store.rows(
            "SELECT id FROM request WHERE account_id = ? ORDER BY id DESC LIMIT ?",
            [actor.account_id, MAX_LIST],
        )
    ]
    views = [_request_view(store, i) for i in ids]
    data = RequestList(requests=views, unread_total=sum(v.unread for v in views))
    return _result(db, data, _all_citations(views))


@guarded
def get_request(
    db: Database, store: DeskStore, actor: Actor, request_id: int
) -> Result[RequestView]:
    _own(store, actor, request_id)
    view = _request_view(store, request_id)
    return _result(db, view, view.answer.citations if view.answer else ())


@guarded
def mark_read(
    db: Database, store: DeskStore, actor: Actor, request_id: int
) -> Result[RequestView]:
    """Mark a request's updates as read (inbox housekeeping, not audited)."""
    _own(store, actor, request_id)
    with store.transaction() as con:
        con.execute(
            "UPDATE request_update SET read = 1 WHERE request_id = ?", [request_id]
        )
    view = _request_view(store, request_id)
    return _result(db, view, view.answer.citations if view.answer else ())


@guarded
def find_published_answers(
    db: Database,
    store: DeskStore,
    query: str | None = None,
    measure: str | None = None,
    court: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 10,
) -> Result[LibraryResults]:
    """Confirmed answers in the public library that match a question or a
    figure, best match first. Entries citing a figure revised since they
    were published say so (``needs_reverification``)."""
    words = {w for w in re.findall(r"[a-z0-9.]+", (query or "").lower()) if len(w) > 2}
    scored: list[tuple[float, LibraryEntryView]] = []
    for row in store.rows(
        "SELECT l.id, l.request_id, l.published_at, q.question, q.needs_reverification "
        "FROM library_entry l JOIN request q ON q.id = l.request_id "
        "ORDER BY l.id DESC LIMIT 500"
    ):
        answer = _answer_view(store, row["request_id"])
        if answer is None:
            continue
        view, _ = answer
        score = 0.0
        if words:
            text = f"{row['question']} {view.text}".lower()
            score += sum(1 for w in words if w in text) / len(words)
        for c in view.citations:
            if (
                (measure is None or c.measure == measure)
                and (court is None or c.court == court)
                and (fiscal_year is None or c.fiscal_year == fiscal_year)
                and (measure or court or fiscal_year)
            ):
                score += 1
                break
        if not (words or measure or court or fiscal_year):
            score = 1  # no filter: list everything, newest first
        if score <= 0:
            continue
        inq = store.one(
            "SELECT inquiry_id FROM inquiry_request WHERE request_id = ?",
            [row["request_id"]],
        )
        scored.append(
            (
                score,
                LibraryEntryView(
                    id=row["id"],
                    request_id=row["request_id"],
                    question=row["question"],
                    answer=view,
                    inquiry=_inquiry_view(store, inq[0]) if inq else None,
                    published_at=row["published_at"],
                    needs_reverification=bool(row["needs_reverification"]),
                ),
            )
        )
    scored.sort(key=lambda s: -s[0])
    entries = [e for _, e in scored[: max(1, min(limit, MAX_LIST))]]
    data = LibraryResults(entries=entries, query=query)
    return _result(db, data, [c for e in entries for c in e.answer.citations])


@guarded
def inquiry_queue(db: Database, store: DeskStore, actor: Actor) -> Result[InquiryQueue]:
    """The statistics office's queue: open inquiries first, most-asked first."""
    _staff(actor)
    rows = store.rows(
        "SELECT i.id FROM inquiry i LEFT JOIN inquiry_request r ON r.inquiry_id = i.id "
        "GROUP BY i.id ORDER BY (i.status = 'waiting_for_office') DESC, "
        "count(r.request_id) DESC, i.id LIMIT ?",
        [MAX_LIST],
    )
    data = InquiryQueue(inquiries=[_inquiry_view(store, r[0]) for r in rows])
    return _result(db, data)


@guarded
def audit_log(
    db: Database, store: DeskStore, actor: Actor, limit: int = 100
) -> Result[AuditLog]:
    """The append-only record of every desk write, newest first (staff)."""
    _staff(actor)
    rows = store.rows(
        "SELECT * FROM audit_event ORDER BY id DESC LIMIT ?", [min(limit, 500)]
    )
    data = AuditLog(
        events=[
            AuditEventView(
                id=r["id"],
                at=r["at"],
                actor=r["actor"],
                tool=r["tool"],
                record=r["record"],
                before=r["before"],
                after=r["after"],
            )
            for r in rows
        ]
    )
    return _result(db, data)


# ── writes ───────────────────────────────────────────────────────────────────


def _insert_request(con: Any, actor: Actor, option: Option, question: str) -> int:
    ts = now()
    cur = con.execute(
        "INSERT INTO request (option, account_id, asker_name, asker_role, question, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'received', ?, ?)",
        [option, actor.account_id, actor.name, actor.role, question, ts, ts],
    )
    rid = int(cur.lastrowid)
    DeskStore.add_update(con, rid, "received", f"Request #{rid} received.")
    DeskStore.audit(
        con, actor.account_id, "open_request", f"request:{rid}", None, "received"
    )
    return rid


@guarded
def open_request(
    db: Database,
    store: DeskStore,
    actor: Actor,
    option: Option,
    question: str,
    idempotency_key: str | None = None,
    confirm: bool = True,
) -> Result[DeskOutcome]:
    """Create a request for one of the three options under an answer."""
    if (done := _replay(store, actor, "open_request", idempotency_key)) is not None:
        return _result(db, done)
    question = _clean(question, MAX_QUESTION, "question")
    _screen_text(db, question)
    if not confirm:
        return _result(
            db,
            DeskOutcome(
                written=False,
                preview=True,
                message="Nothing written yet. Confirm to create a "
                f'"{OPTION_LABELS[option]}" '
                "request for this question.",
            ),
        )
    with store.transaction() as con:
        rid = _insert_request(con, actor, option, question)
        outcome = DeskOutcome(
            written=True,
            message=f"Request #{rid} created. Save the verified answer next.",
            request=None,
        )
        DeskStore.remember(
            con,
            actor.account_id,
            "open_request",
            idempotency_key,
            outcome.model_dump_json(),
        )
    outcome.request = _request_view(store, rid)
    return _result(db, outcome)


def _save_answer(
    con: Any, actor: Actor, request: Any, text: str, gate: GateReport
) -> None:
    rid = int(request["id"])
    version_row = con.execute(
        "SELECT coalesce(max(version), 0) FROM answer WHERE request_id = ?", [rid]
    ).fetchone()
    version = int(version_row[0]) + 1
    cur = con.execute(
        "INSERT INTO answer (request_id, version, text, edition_basis, verified_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [rid, version, text, ",".join(gate.edition_basis), now()],
    )
    aid = int(cur.lastrowid)
    for i, c in enumerate(gate.citations):
        con.execute(
            "INSERT INTO citation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                aid,
                i,
                c.model_dump_json(),
                c.measure,
                c.court,
                c.fiscal_year,
                c.edition,
                c.value,
            ],
        )
    before = request["status"]
    if before == "received":
        new = "watching" if request["option"] == "notify" else "verified"
        status_rules.check(before, new)
        DeskStore.set_status(con, rid, new)
        text_update = (
            "Verified answer saved. You'll be notified if a newer edition revises "
            "any figure in it."
            if new == "watching"
            else "Verified answer saved: " + _stamp(gate.edition_basis, rid)
        )
        DeskStore.add_update(con, rid, new, text_update)
    else:
        new = before
        DeskStore.add_update(
            con,
            rid,
            "verified",
            f"Answer updated to version {version} and re-verified.",
        )
    DeskStore.audit(
        con,
        actor.account_id,
        "save_verified_answer",
        f"request:{rid}:answer:{version}",
        before,
        new,
    )


@guarded
def save_verified_answer(
    db: Database,
    store: DeskStore,
    actor: Actor,
    request_id: int,
    text: str,
    citations: Sequence[CitationIn],
    idempotency_key: str | None = None,
    confirm: bool = True,
) -> Result[DeskOutcome]:
    """Run the verification gate on an answer and save it only if it passes."""
    if (
        done := _replay(store, actor, "save_verified_answer", idempotency_key)
    ) is not None:
        return _result(db, done)
    request = _own(store, actor, request_id)
    if request["status"] == "published":
        raise InvalidTransitionError(
            f"Request #{request_id} is published; its answer can't change.",
        )
    text = _clean(text, MAX_ANSWER, "answer")
    gate = verify(db, text, citations)
    if not gate.passed:
        return _result(
            db,
            DeskOutcome(
                written=False,
                message="Not saved: the answer didn't pass verification. "
                + " ".join(p.message for p in gate.problems[:3]),
                gate=gate,
            ),
            gate.citations,
        )
    _screen_text(db, text)
    if not confirm:
        return _result(
            db,
            DeskOutcome(
                written=False,
                preview=True,
                message="The answer passes verification. Nothing written yet; "
                "confirm to save it.",
                gate=gate,
            ),
            gate.citations,
        )
    with store.transaction() as con:
        _save_answer(con, actor, request, text, gate)
        outcome = DeskOutcome(
            written=True,
            message=f"Verified answer saved to request #{request_id}.",
            gate=gate,
        )
        DeskStore.remember(
            con,
            actor.account_id,
            "save_verified_answer",
            idempotency_key,
            outcome.model_dump_json(),
        )
    outcome.request = _request_view(store, request_id)
    return _result(db, outcome, gate.citations)


def _attach_inquiry(
    con: Any, actor: Actor, request_id: int, e: Eligibility, status_before: str
) -> tuple[int, bool]:
    """Find or create the inquiry for ``e``'s revision and attach the request.
    Returns (inquiry id, whether it was new)."""
    row = con.execute(
        "SELECT id, status FROM inquiry WHERE measure = ? AND court = ? "
        "AND fiscal_year = ? AND from_edition = ? AND to_edition = ?",
        [e.measure, e.court, e.fiscal_year, e.from_edition, e.to_edition],
    ).fetchone()
    new = row is None
    if new:
        cur = con.execute(
            "INSERT INTO inquiry (measure, court, fiscal_year, from_edition, "
            "from_value, "
            "to_edition, to_value, route, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting_for_office', ?)",
            [
                e.measure,
                e.court,
                e.fiscal_year,
                e.from_edition,
                e.from_value,
                e.to_edition,
                e.to_value,
                route_for("official_table"),
                now(),
            ],
        )
        iid, inquiry_status = int(cur.lastrowid), "waiting_for_office"
        DeskStore.audit(
            con,
            actor.account_id,
            "file_revision_inquiry",
            f"inquiry:{iid}",
            None,
            inquiry_status,
        )
    else:
        iid, inquiry_status = int(row[0]), str(row[1])
    con.execute(
        "INSERT OR IGNORE INTO inquiry_request VALUES (?, ?)", [iid, request_id]
    )
    others = int(
        con.execute(
            "SELECT count(*) - 1 FROM inquiry_request WHERE inquiry_id = ?", [iid]
        ).fetchone()[0]
    )
    target = (
        "office_responded"
        if inquiry_status == "office_responded"
        else "waiting_for_office"
    )
    status_rules.check(status_before, target)
    DeskStore.set_status(con, request_id, target)
    change = (
        f"FY{e.fiscal_year} {get_measure(e.measure).label}, {_court_name(e.court)}: "
        f"{fmt(e.from_value or 0)} ({e.from_edition}) → "
        f"{fmt(e.to_value or 0)} ({e.to_edition})"
    )
    if target == "office_responded":
        text = (
            f"The statistics office already answered this question ({change}). "
            "The response is attached to your request."
        )
        kind = "inquiry_joined"
    else:
        waiting = (
            f" {others} other request{'s are' if others != 1 else ' is'} waiting on "
            "the same question."
            if others
            else ""
        )
        text = (
            f"Sent to the statistics office: why {change} changed. "
            f"(Sandbox: recorded here, not sent.){waiting}"
        )
        kind = "inquiry_filed" if new else "inquiry_joined"
    DeskStore.add_update(con, request_id, kind, text)
    DeskStore.audit(
        con,
        actor.account_id,
        "file_revision_inquiry",
        f"request:{request_id}",
        status_before,
        target,
    )
    return iid, new


@guarded
def file_revision_inquiry(
    db: Database,
    store: DeskStore,
    actor: Actor,
    request_id: int,
    measure: str,
    court: str,
    fiscal_year: int,
    idempotency_key: str | None = None,
    confirm: bool = True,
) -> Result[DeskOutcome]:
    """Ask the statistics office why a figure in the request's answer changed.
    One inquiry per revision: a later asker is attached to the existing one."""
    if (
        done := _replay(store, actor, "file_revision_inquiry", idempotency_key)
    ) is not None:
        return _result(db, done)
    request = _own(store, actor, request_id)
    if request["option"] != "ask_office":
        raise NotEligibleError(
            f'Request #{request_id} was saved as "{OPTION_LABELS[request["option"]]}". '
            'Use "Ask the statistics office why this changed" on the answer instead.',
        )
    if request["status"] != "verified":
        raise InvalidTransitionError(
            f"Request #{request_id} needs a verified answer, and no inquiry yet, "
            f"before it can go to the statistics office (it is '{request['status']}').",
            ["save_verified_answer"],
        )
    cited = store.one(
        "SELECT 1 FROM citation c JOIN answer a ON a.id = c.answer_id "
        "WHERE a.request_id = ? AND c.measure = ? AND c.court = ? "
        "AND c.fiscal_year = ?",
        [request_id, measure, court, fiscal_year],
    )
    if cited is None:
        raise NotEligibleError(
            "The verified answer doesn't cite that figure; ask about a figure the "
            "answer quotes.",
        )
    e = _eligibility(db, measure, court, fiscal_year)
    if not e.eligible:
        raise NotEligibleError(e.reason)
    if not confirm:
        return _result(
            db,
            DeskOutcome(
                written=False,
                preview=True,
                message="Nothing written yet. Confirm to ask the statistics office "
                "why "
                f"FY{fiscal_year} {get_measure(measure).label} changed from "
                f"{fmt(e.from_value or 0)} ({e.from_edition}) to "
                f"{fmt(e.to_value or 0)} ({e.to_edition}). Sandbox: nothing is sent.",
            ),
        )
    with store.transaction() as con:
        iid, new = _attach_inquiry(con, actor, request_id, e, request["status"])
        outcome = DeskOutcome(
            written=True,
            message=(f"Inquiry #{iid} filed. " if new else f"Added to inquiry #{iid}. ")
            + f"It would go to {ROUTE_LABELS[route_for('official_table')]}. "
            "Sandbox: recorded here, not sent.",
        )
        DeskStore.remember(
            con,
            actor.account_id,
            "file_revision_inquiry",
            idempotency_key,
            outcome.model_dump_json(),
        )
    outcome.request = _request_view(store, request_id)
    outcome.inquiry = _inquiry_view(store, iid)
    return _result(db, outcome)


@guarded
def record_official_response(
    db: Database,
    store: DeskStore,
    actor: Actor,
    inquiry_id: int,
    outcome: Outcome,
    text: str,
    idempotency_key: str | None = None,
    confirm: bool = True,
) -> Result[DeskOutcome]:
    """Record the statistics office's answer to an inquiry (staff only) and
    tell everyone waiting on it."""
    _staff(actor)
    if (
        done := _replay(store, actor, "record_official_response", idempotency_key)
    ) is not None:
        return _result(db, done)
    inquiry = _inquiry_view(store, inquiry_id)
    if inquiry.status != "waiting_for_office":
        raise InvalidTransitionError(f"Inquiry #{inquiry_id} already has a response.")
    text = _clean(text, MAX_ANSWER, "response")
    _screen_text(db, text)
    if not confirm:
        return _result(
            db,
            DeskOutcome(
                written=False,
                preview=True,
                message=f"Nothing written yet. Confirm to record this response and "
                f"notify {inquiry.waiting_requests} waiting request(s).",
                inquiry=inquiry,
            ),
        )
    with store.transaction() as con:
        con.execute(
            "INSERT INTO response (inquiry_id, outcome, text, entered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [inquiry_id, outcome, text, actor.name, now()],
        )
        con.execute(
            "UPDATE inquiry SET status = 'office_responded' WHERE id = ?", [inquiry_id]
        )
        DeskStore.audit(
            con,
            actor.account_id,
            "record_official_response",
            f"inquiry:{inquiry_id}",
            "waiting_for_office",
            "office_responded",
        )
        waiting = con.execute(
            "SELECT q.id, q.status FROM request q JOIN inquiry_request r "
            "ON r.request_id = q.id WHERE r.inquiry_id = ?",
            [inquiry_id],
        ).fetchall()
        for rid, st in waiting:
            if st == "waiting_for_office":
                status_rules.check(st, "office_responded")
                DeskStore.set_status(con, rid, "office_responded")
                DeskStore.audit(
                    con,
                    actor.account_id,
                    "record_official_response",
                    f"request:{rid}",
                    st,
                    "office_responded",
                )
            DeskStore.add_update(
                con,
                rid,
                "office_responded",
                f"The statistics office {outcome} the figure and explained the "
                f"change: {text} (Simulated statistics office, sandbox.)",
                dedup=f"response:{inquiry_id}",
            )
        result = DeskOutcome(
            written=True,
            message=f"Response recorded for inquiry #{inquiry_id}; "
            f"{len(waiting)} request(s) updated.",
        )
        DeskStore.remember(
            con,
            actor.account_id,
            "record_official_response",
            idempotency_key,
            result.model_dump_json(),
        )
    result.inquiry = _inquiry_view(store, inquiry_id)
    return _result(db, result)


@guarded
def publish_answer(
    db: Database,
    store: DeskStore,
    actor: Actor,
    request_id: int,
    idempotency_key: str | None = None,
    confirm: bool = True,
) -> Result[DeskOutcome]:
    """Approve a request's verified answer into the public library (staff
    only; the agent can never approve)."""
    _staff(actor)
    if (done := _replay(store, actor, "publish_answer", idempotency_key)) is not None:
        return _result(db, done)
    request = _own(store, actor, request_id)
    answer = _answer_view(store, request_id)
    if answer is None:
        raise InvalidTransitionError(
            f"Request #{request_id} has no verified answer to publish.",
            ["save_verified_answer"],
        )
    status_rules.check(request["status"], "published")
    if not confirm:
        return _result(
            db,
            DeskOutcome(
                written=False,
                preview=True,
                message="Nothing written yet. Confirm to publish request "
                f"#{request_id}'s "
                "answer to the public library.",
            ),
            answer[0].citations,
        )
    with store.transaction() as con:
        con.execute(
            "INSERT INTO library_entry "
            "(request_id, answer_id, published_by, published_at) "
            "VALUES (?, ?, ?, ?)",
            [request_id, answer[1], actor.name, now()],
        )
        DeskStore.set_status(con, request_id, "published")
        DeskStore.add_update(
            con,
            request_id,
            "published",
            "Approved and published to the public library. The next person who asks "
            "gets this answer.",
        )
        DeskStore.audit(
            con,
            actor.account_id,
            "publish_answer",
            f"request:{request_id}",
            request["status"],
            "published",
        )
        outcome = DeskOutcome(
            written=True, message=f"Request #{request_id} published to the library."
        )
        DeskStore.remember(
            con,
            actor.account_id,
            "publish_answer",
            idempotency_key,
            outcome.model_dump_json(),
        )
    outcome.request = _request_view(store, request_id)
    return _result(db, outcome, answer[0].citations)


@guarded
def submit_option(
    db: Database,
    store: DeskStore,
    actor: Actor,
    option: Option,
    question: str,
    answer_text: str,
    citations: Sequence[CitationIn],
    inquiry: CitationIn | None = None,
    idempotency_key: str | None = None,
) -> Result[DeskOutcome]:
    """What one click on an option does: verify the answer first, then, only
    if it passes, create the request, save the answer and (for *Ask the
    statistics office*) file the inquiry, in one transaction."""
    if (done := _replay(store, actor, "submit_option", idempotency_key)) is not None:
        return _result(db, done)
    question = _clean(question, MAX_QUESTION, "question")
    text = _clean(answer_text, MAX_ANSWER, "answer")
    _screen_text(db, question)
    gate = verify(db, text, citations)
    if not gate.passed:
        return _result(
            db,
            DeskOutcome(
                written=False,
                message="Not saved: the answer didn't pass verification. "
                + " ".join(p.message for p in gate.problems[:3]),
                gate=gate,
            ),
            gate.citations,
        )
    _screen_text(db, text)
    e: Eligibility | None = None
    if option == "ask_office":
        if inquiry is None:
            raise NotEligibleError(
                "Say which figure to ask the statistics office about."
            )
        if not any(
            (c.measure, c.court, c.fiscal_year)
            == (inquiry.measure, inquiry.court, inquiry.fiscal_year)
            for c in gate.citations
        ):
            raise NotEligibleError(
                "The answer doesn't quote that figure; ask about a figure it quotes."
            )
        e = _eligibility(db, inquiry.measure, inquiry.court, inquiry.fiscal_year)
        if not e.eligible:
            raise NotEligibleError(e.reason)
    iid: int | None = None
    with store.transaction() as con:
        rid = _insert_request(con, actor, option, question)
        req = con.execute("SELECT * FROM request WHERE id = ?", [rid]).fetchone()
        _save_answer(con, actor, req, text, gate)
        if e is not None:
            iid, _ = _attach_inquiry(con, actor, rid, e, "verified")
        message = {
            "ask_office": f"Request #{rid}: verified answer saved and the question "
            "filed with the statistics office (sandbox: not sent).",
            "verified_copy": f"Request #{rid}: verified copy saved.",
            "notify": f"Request #{rid}: verified answer saved; you'll be notified if a "
            "newer edition revises a figure in it.",
        }[option]
        outcome = DeskOutcome(written=True, message=message, gate=gate)
        DeskStore.remember(
            con,
            actor.account_id,
            "submit_option",
            idempotency_key,
            outcome.model_dump_json(),
        )
    outcome.request = _request_view(store, rid)
    if iid is not None:
        outcome.inquiry = _inquiry_view(store, iid)
    return _result(db, outcome, gate.citations)


@guarded
def check_staleness(db: Database, store: DeskStore) -> Result[StalenessReport]:
    """Compare every saved citation with the catalog. A figure a newer edition
    printed differently flags library answers for re-verification and tells
    askers who chose *Notify me* (``make desk-check``; also run at startup)."""
    checked = flagged = created = 0
    rows = store.rows(
        "SELECT q.id, q.option, q.status, c.record FROM request q "
        "JOIN answer a ON a.request_id = q.id "
        "JOIN citation c ON c.answer_id = a.id "
        "WHERE a.version = (SELECT max(version) FROM answer WHERE request_id = q.id) "
        "AND q.status IN ('watching', 'published')"
    )
    with store.transaction() as con:
        for rid, option, st, record in rows:
            c = CheckedCitation.model_validate_json(record)
            if c.historical:
                continue
            checked += 1
            chain = load_chain(db, c.measure, c.court, c.fiscal_year)
            cited = next((r for r in chain if r.edition == c.edition), None)
            if cited is None:
                continue
            newer = [
                r for r in chain if r.pub_order > cited.pub_order and r.shown != c.value
            ]
            if not newer:
                continue
            latest = newer[-1]
            text = (
                f"A figure in your answer was revised: FY{c.fiscal_year} "
                f"{c.measure_label}, {_court_name(c.court)} is {fmt(latest.shown)} in "
                f"{latest.edition}, not the {fmt(c.value)} ({c.edition}) your answer "
                "quotes. Review the answer before relying on it."
            )
            key = f"revised:{c.measure}:{c.court}:{c.fiscal_year}:{latest.edition}"
            if st == "published":
                cur = con.execute(
                    "UPDATE request SET needs_reverification = 1 WHERE id = ? "
                    "AND needs_reverification = 0",
                    [rid],
                )
                if cur.rowcount:
                    flagged += 1
                    DeskStore.audit(
                        con,
                        "system",
                        "check_staleness",
                        f"request:{rid}",
                        "current",
                        "needs_reverification",
                    )
            if (option == "notify" or st == "published") and DeskStore.add_update(
                con, rid, "figure_revised", text, dedup=key
            ):
                created += 1
    data = StalenessReport(
        citations_checked=checked,
        library_entries_flagged=flagged,
        updates_created=created,
    )
    return _result(db, data)
