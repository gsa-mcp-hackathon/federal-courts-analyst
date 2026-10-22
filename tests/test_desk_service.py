"""The request desk end to end in the core (ADR 0013): the three options,
statuses, roles, inquiries, idempotency, staleness, the audit log, and an
office response showing up in the read tools."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from courts_analyst.core.desk import hooks
from courts_analyst.core.desk import service as desk
from courts_analyst.core.desk.errors import (
    DeskForbiddenError,
    DeskNotFoundError,
    InvalidTransitionError,
    NotEligibleError,
)
from courts_analyst.core.desk.models import Actor, CitationIn, InquiryTarget
from courts_analyst.core.desk.store import FIRST_REQUEST_ID, DeskStore
from courts_analyst.core.official import get_official_figure

W = "weighted_civil_filings_per_judgeship"
PRIYA = Actor(account_id="priya", name="Priya", role="congressional_staff")
SAM = Actor(account_id="sam", name="Sam", role="journalist")
OFFICE = Actor(
    account_id="office", name="Stats Office", role="statistics_office", staff=True
)
QUESTION = "How has the national weighted civil filings per judgeship changed?"
ANSWER = (
    "National weighted civil filings per judgeship were 322 in FY2020 and 318 in "
    "FY2021 (JFF-2024). FY2020 was first published as 554 (JB-2020)."
)
CITES = [
    CitationIn(measure=W, fiscal_year=2020, edition="JFF-2024", value=322),
    CitationIn(measure=W, fiscal_year=2021, edition="JFF-2024", value=318),
    CitationIn(measure=W, fiscal_year=2020, edition="JB-2020", value=554),
]
FY2020 = InquiryTarget(measure=W, fiscal_year=2020)


@pytest.fixture
def store() -> Iterator[DeskStore]:
    s = DeskStore()
    yield s
    hooks.set_active_store(None)
    s.close()


def ask_office(db: Any, store: DeskStore, actor: Actor = PRIYA, **kw: Any) -> Any:
    return desk.submit_option(
        db, store, actor, "ask_office", QUESTION, ANSWER, CITES, inquiry=FY2020, **kw
    )


def audit_count(store: DeskStore) -> int:
    row = store.one("SELECT count(*) FROM audit_event")
    return int(row[0]) if row else 0


# ── the three options ────────────────────────────────────────────────────────


def test_ask_office_saves_and_files_an_inquiry(core_db: Any, store: DeskStore) -> None:
    r = ask_office(core_db, store)
    assert r.status == "ok"
    out = r.data
    assert out.written and out.request and out.inquiry
    assert out.request.id == FIRST_REQUEST_ID
    assert out.request.status == "waiting_for_office"
    assert out.request.answer.edition_basis == ["JFF-2024"]
    assert "Verified" in out.request.answer.stamp
    assert (out.inquiry.from_value, out.inquiry.to_value) == (554, 322)
    assert out.inquiry.route == "ao_statistics"
    assert "not sent" in out.inquiry.delivery
    kinds = [u.kind for u in out.request.updates]
    assert kinds[:3] == ["inquiry_filed", "verified", "received"]
    assert any(w.code == "sandbox" for w in r.warnings)


def test_verified_copy_and_notify(core_db: Any, store: DeskStore) -> None:
    copy = desk.submit_option(
        core_db, store, PRIYA, "verified_copy", QUESTION, ANSWER, CITES
    ).data
    watch = desk.submit_option(
        core_db, store, PRIYA, "notify", QUESTION, ANSWER, CITES
    ).data
    assert copy.request.status == "verified" and copy.inquiry is None
    assert watch.request.status == "watching"
    mine = desk.my_requests(core_db, store, PRIYA).data
    assert [r.id for r in mine.requests] == [watch.request.id, copy.request.id]
    assert mine.unread_total == 4


def test_failed_gate_writes_nothing(core_db: Any, store: DeskStore) -> None:
    bad = [
        CitationIn(measure=W, fiscal_year=2020, edition="JB-2020", value=554),
        CitationIn(measure=W, fiscal_year=2021, edition="JFF-2024", value=318),
    ]
    r = desk.submit_option(
        core_db,
        store,
        PRIYA,
        "verified_copy",
        QUESTION,
        "National weighted civil filings were 554 in FY2020 and 318 in FY2021.",
        bad,
    )
    assert not r.data.written and not r.data.gate.passed
    assert "didn't pass verification" in r.data.message
    assert audit_count(store) == 0
    assert store.one("SELECT count(*) FROM request")[0] == 0


# ── one inquiry per revision; responses reach everyone ──────────────────────


def test_second_asker_joins_the_same_inquiry(core_db: Any, store: DeskStore) -> None:
    first = ask_office(core_db, store).data
    second = ask_office(core_db, store, SAM).data
    assert second.inquiry.id == first.inquiry.id
    assert second.inquiry.waiting_requests == 2
    assert "1 other request is waiting" in second.request.updates[0].text
    queue = desk.inquiry_queue(core_db, store, OFFICE).data
    assert [i.waiting_requests for i in queue.inquiries] == [2]


def test_office_response_updates_everyone_and_the_read_tools(
    core_db: Any, store: DeskStore
) -> None:
    hooks.set_active_store(store)
    first = ask_office(core_db, store).data
    ask_office(core_db, store, SAM)
    r = desk.record_official_response(
        core_db,
        store,
        OFFICE,
        first.inquiry.id,
        "confirmed",
        "The 2023 revision re-weighted directly filed MDL cases.",
    ).data
    assert r.written and r.inquiry.status == "office_responded"
    for actor in (PRIYA, SAM):
        req = desk.my_requests(core_db, store, actor).data.requests[0]
        assert req.status == "office_responded"
        assert req.updates[0].kind == "office_responded"
        assert "Simulated statistics office" in req.updates[0].text

    fig = get_official_figure(core_db, W, "US", 2020)
    notes = {n.basis: n.text for n in fig.data.revision_notes}
    assert "office_response" in notes
    assert "simulated statistics office (sandbox" in notes["office_response"]
    assert "re-weighted directly filed MDL cases" in notes["office_response"]

    # A later asker gets the answer at once.
    third = ask_office(
        core_db, store, Actor(account_id="r", name="R", role="researcher")
    )
    assert third.data.request.status == "office_responded"
    assert third.data.request.updates[0].kind == "inquiry_joined"


def test_without_a_store_the_read_tools_are_unchanged(core_db: Any) -> None:
    hooks.set_active_store(None)
    fig = get_official_figure(core_db, W, "US", 2020)
    assert {n.basis for n in fig.data.revision_notes} <= {"official", "inferred"}


def test_publish_and_find_in_the_library(core_db: Any, store: DeskStore) -> None:
    first = ask_office(core_db, store).data
    desk.record_official_response(
        core_db, store, OFFICE, first.inquiry.id, "confirmed", "Explained."
    )
    pub = desk.publish_answer(core_db, store, OFFICE, first.request.id).data
    assert pub.request.status == "published" and pub.request.published
    found = desk.find_published_answers(
        core_db, store, query="weighted civil filings changed"
    ).data
    assert [e.request_id for e in found.entries] == [first.request.id]
    assert found.entries[0].inquiry.response.text == "Explained."
    by_figure = desk.find_published_answers(
        core_db, store, measure=W, court="US", fiscal_year=2020
    ).data
    assert len(by_figure.entries) == 1
    none = desk.find_published_answers(core_db, store, query="bankruptcy wiretap").data
    assert none.entries == []


# ── eligibility ──────────────────────────────────────────────────────────────


def test_eligibility(core_db: Any) -> None:
    yes = desk.inquiry_eligibility(core_db, W, "US", 2020).data
    assert yes.eligible and (yes.from_value, yes.to_value) == (554, 322)
    pending = desk.inquiry_eligibility(core_db, "civil_cases_pending", "AK", 2016).data
    assert not pending.eligible and "Table C-1" in pending.reason
    unrevised = desk.inquiry_eligibility(
        core_db, "civil_cases_pending", "US", 2023
    ).data
    assert not unrevised.eligible and "wasn't revised" in unrevised.reason


def test_inquiry_needs_a_cited_unexplained_revision(
    core_db: Any, store: DeskStore
) -> None:
    rid = desk.open_request(
        core_db, store, PRIYA, "ask_office", QUESTION
    ).data.request.id
    with pytest.raises(InvalidTransitionError):
        desk.file_revision_inquiry(core_db, store, PRIYA, rid, W, "US", 2020)
    desk.save_verified_answer(core_db, store, PRIYA, rid, ANSWER, CITES)
    with pytest.raises(NotEligibleError, match="doesn't cite"):
        desk.file_revision_inquiry(core_db, store, PRIYA, rid, W, "US", 2023)
    ok = desk.file_revision_inquiry(core_db, store, PRIYA, rid, W, "US", 2020).data
    assert ok.written and ok.request.status == "waiting_for_office"
    with pytest.raises(InvalidTransitionError):
        desk.file_revision_inquiry(core_db, store, PRIYA, rid, W, "US", 2021)


def test_inquiry_only_from_the_ask_office_option(
    core_db: Any, store: DeskStore
) -> None:
    copy = desk.submit_option(
        core_db, store, PRIYA, "verified_copy", QUESTION, ANSWER, CITES
    ).data.request
    with pytest.raises(NotEligibleError, match="Ask the statistics office"):
        desk.file_revision_inquiry(core_db, store, PRIYA, copy.id, W, "US", 2020)


def test_ask_office_needs_an_eligible_figure(core_db: Any, store: DeskStore) -> None:
    with pytest.raises(NotEligibleError):
        desk.submit_option(
            core_db, store, PRIYA, "ask_office", QUESTION, ANSWER, CITES, inquiry=None
        )
    assert audit_count(store) == 0


# ── roles ────────────────────────────────────────────────────────────────────


def test_staff_actions_refuse_the_public(core_db: Any, store: DeskStore) -> None:
    first = ask_office(core_db, store).data
    with pytest.raises(DeskForbiddenError):
        desk.record_official_response(
            core_db, store, PRIYA, first.inquiry.id, "confirmed", "Self-approved."
        )
    with pytest.raises(DeskForbiddenError):
        desk.publish_answer(core_db, store, PRIYA, first.request.id)
    with pytest.raises(DeskForbiddenError):
        desk.inquiry_queue(core_db, store, PRIYA)
    with pytest.raises(DeskForbiddenError):
        desk.audit_log(core_db, store, PRIYA)


def test_requests_are_private_to_their_asker(core_db: Any, store: DeskStore) -> None:
    rid = ask_office(core_db, store).data.request.id
    with pytest.raises(DeskForbiddenError):
        desk.get_request(core_db, store, SAM, rid)
    assert desk.get_request(core_db, store, OFFICE, rid).data.id == rid
    with pytest.raises(DeskNotFoundError):
        desk.get_request(core_db, store, PRIYA, 9999)
    assert desk.my_requests(core_db, store, SAM).data.requests == []


def test_judge_and_party_requests_are_declined_before_writing(
    core_db: Any, store: DeskStore
) -> None:
    for question in (
        "Which judge in the Northern District of Florida is the slowest?",
        "List the plaintiffs' names in the 3M earplug MDL.",
    ):
        r = desk.open_request(core_db, store, PRIYA, "verified_copy", question)
        assert r.status == "declined"
    assert audit_count(store) == 0


# ── statuses, previews, idempotency, audit ───────────────────────────────────


def test_invalid_transitions(core_db: Any, store: DeskStore) -> None:
    first = ask_office(core_db, store).data
    with pytest.raises(InvalidTransitionError):
        desk.publish_answer(core_db, store, OFFICE, first.request.id)  # still waiting
    desk.record_official_response(
        core_db, store, OFFICE, first.inquiry.id, "corrected", "Corrected."
    )
    with pytest.raises(InvalidTransitionError):
        desk.record_official_response(
            core_db, store, OFFICE, first.inquiry.id, "confirmed", "Again."
        )
    desk.publish_answer(core_db, store, OFFICE, first.request.id)
    with pytest.raises(InvalidTransitionError):
        desk.save_verified_answer(
            core_db, store, PRIYA, first.request.id, ANSWER, CITES
        )


def test_preview_writes_nothing(core_db: Any, store: DeskStore) -> None:
    r = desk.open_request(core_db, store, PRIYA, "notify", QUESTION, confirm=False)
    assert r.data.preview and not r.data.written
    assert audit_count(store) == 0


def test_idempotency_key_replays_instead_of_writing(
    core_db: Any, store: DeskStore
) -> None:
    a = ask_office(core_db, store, idempotency_key="k1").data
    n = audit_count(store)
    b = ask_office(core_db, store, idempotency_key="k1").data
    assert audit_count(store) == n
    assert b.message.startswith("Already done")
    assert store.one("SELECT count(*) FROM request")[0] == 1
    assert a.written


def test_every_write_is_audited_and_the_log_is_append_only(
    core_db: Any, store: DeskStore
) -> None:
    first = ask_office(core_db, store).data
    desk.record_official_response(
        core_db, store, OFFICE, first.inquiry.id, "confirmed", "Explained."
    )
    desk.publish_answer(core_db, store, OFFICE, first.request.id)
    tools = [e.tool for e in desk.audit_log(core_db, store, OFFICE).data.events]
    assert set(tools) >= {
        "open_request",
        "save_verified_answer",
        "file_revision_inquiry",
        "record_official_response",
        "publish_answer",
    }
    with store.transaction() as con, pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE audit_event SET actor = 'x'")
    with store.transaction() as con, pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM audit_event")


def test_mark_read(core_db: Any, store: DeskStore) -> None:
    rid = ask_office(core_db, store).data.request.id
    assert desk.get_request(core_db, store, PRIYA, rid).data.unread == 3
    assert desk.mark_read(core_db, store, PRIYA, rid).data.unread == 0


# ── staleness ────────────────────────────────────────────────────────────────


def test_staleness_flags_library_answers_and_notifies_watchers(
    core_db: Any, store: DeskStore
) -> None:
    # Quoting the JB-2020 printing consistently passes the gate, but later
    # editions print 322: the answer is out of date.
    old_text = "In JB-2020, FY2020 national weighted civil filings were 554."
    old = [CitationIn(measure=W, fiscal_year=2020, edition="JB-2020", value=554)]
    watch = desk.submit_option(core_db, store, PRIYA, "notify", QUESTION, old_text, old)
    copy = desk.submit_option(
        core_db, store, SAM, "verified_copy", QUESTION, old_text, old
    )
    desk.publish_answer(core_db, store, OFFICE, copy.data.request.id)
    report = desk.check_staleness(core_db, store).data
    assert report.library_entries_flagged == 1
    assert report.updates_created == 2
    again = desk.check_staleness(core_db, store).data
    assert again.updates_created == 0 and again.library_entries_flagged == 0
    w = desk.get_request(core_db, store, PRIYA, watch.data.request.id).data
    assert w.updates[0].kind == "figure_revised"
    assert "322" in w.updates[0].text
    lib = desk.find_published_answers(core_db, store).data.entries
    assert lib[0].needs_reverification


def test_history_citations_never_go_stale(core_db: Any, store: DeskStore) -> None:
    desk.submit_option(core_db, store, PRIYA, "notify", QUESTION, ANSWER, CITES)
    assert desk.check_staleness(core_db, store).data.updates_created == 0
