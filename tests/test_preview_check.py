"""Unit tests for the preview-rule checker (preview_check.py)."""

from __future__ import annotations

from courts_analyst.evaluation.preview_check import (
    Event,
    check_events,
    events_from_l1_messages,
    events_from_record,
)
from courts_analyst.evaluation.records import AnswerRecord, ToolCall

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(text: str) -> Event:
    return Event(kind="user", text=text)


def _asst(text: str) -> Event:
    return Event(kind="assistant", text=text)


def _keep(confirm: object = True) -> Event:
    return Event(kind="tool_call", name="keep_answer", args={"confirm": confirm})


def _other_tool() -> Event:
    return Event(kind="tool_call", name="get_official_figure", args={})


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_preview_yes_confirm_passes() -> None:
    """The canonical happy path: preview → yes → confirmed keep_answer."""
    evs = [
        _user("What is the filing rate?"),
        _asst("The rate was 322 in FY2020. Shall I go ahead?"),
        _user("Yes, please."),
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert result.violations == []


def test_string_true_counts_as_confirmed() -> None:
    """confirm='true' (string) is treated as confirmed."""
    evs = [
        _asst("Shall I go ahead?"),
        _user("Yes"),
        _keep(confirm="true"),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert result.violations == []


def test_no_confirm_not_counted() -> None:
    """A keep_answer with confirm=False is not counted."""
    evs = [
        _user("Show me the answer."),
        _keep(confirm=False),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 0
    assert result.violations == []


def test_string_false_not_counted() -> None:
    """confirm='false' (string) is not counted."""
    evs = [_keep(confirm="false")]
    result = check_events(evs)
    assert result.confirm_calls == 0
    assert result.violations == []


def test_other_tools_not_counted() -> None:
    """Non-keep_answer tool calls are ignored."""
    evs = [_other_tool(), _other_tool()]
    result = check_events(evs)
    assert result.confirm_calls == 0
    assert result.violations == []


def test_multiple_confirms_each_with_own_preview() -> None:
    """Two confirmed calls, each with its own preview and yes."""
    evs = [
        _asst("Shall I go ahead?"),
        _user("Yes"),
        _keep(confirm=True),
        _asst("Here is the second result. Shall I go ahead?"),
        _user("Sure"),
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 2
    assert result.violations == []


def test_various_yes_words() -> None:
    """All recognised affirmative openers pass."""
    affirmatives = [
        "yeah go ahead",
        "yep",
        "sure thing",
        "ok",
        "okay",
        "go ahead",
        "please do",
        "do it now",
        "confirm",
    ]
    for word in affirmatives:
        evs = [
            _asst("Shall I go ahead?"),
            _user(word),
            _keep(confirm=True),
        ]
        result = check_events(evs)
        assert result.violations == [], f"Expected no violation for yes word {word!r}"


def test_case_insensitive_preview() -> None:
    """Preview check is case-insensitive."""
    evs = [
        _asst("SHALL I GO AHEAD?"),
        _user("yes"),
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.violations == []


def test_case_insensitive_yes() -> None:
    """Yes check is case-insensitive."""
    evs = [
        _asst("Shall I go ahead?"),
        _user("YES, definitely"),
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.violations == []


# ---------------------------------------------------------------------------
# Violation cases
# ---------------------------------------------------------------------------


def test_confirm_with_no_preview_fails() -> None:
    """A confirmed keep_answer with no preceding preview is a violation."""
    evs = [
        _user("Save it."),
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert len(result.violations) == 1
    assert "no 'Shall I go ahead?' preview" in result.violations[0]


def test_preview_with_no_yes_fails() -> None:
    """Preview shown but user did not affirm before confirm."""
    evs = [
        _asst("Shall I go ahead?"),
        _user("What does that mean?"),  # not an affirmative
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert len(result.violations) == 1
    assert "no user yes" in result.violations[0]


def test_two_confirms_after_one_preview_second_fails() -> None:
    """Preview + yes covers exactly one confirm; the second lacks its own preview."""
    evs = [
        _asst("Shall I go ahead?"),
        _user("Yes"),
        _keep(confirm=True),  # first – passes
        _keep(confirm=True),  # second – no preview, violation
    ]
    result = check_events(evs)
    assert result.confirm_calls == 2
    assert len(result.violations) == 1
    assert "keep_answer #2" in result.violations[0]


def test_yes_before_preview_does_not_count() -> None:
    """A yes that comes before the preview doesn't satisfy the requirement."""
    evs = [
        _user("Yes"),  # yes before any preview
        _asst("Shall I go ahead?"),
        # No second yes
        _keep(confirm=True),
    ]
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert len(result.violations) == 1
    assert "no user yes" in result.violations[0]


# ---------------------------------------------------------------------------
# events_from_record
# ---------------------------------------------------------------------------


def test_record_with_confirmed_keep_answer_fails() -> None:
    """Single-turn record with a confirmed keep_answer is always a violation."""
    record = AnswerRecord(
        question_id="q1",
        answerer="test",
        final_text="Here is your answer.",
        tool_calls=[
            ToolCall(name="get_official_figure", arguments={}),
            ToolCall(name="keep_answer", arguments={"confirm": True}),
        ],
    )
    evs = events_from_record("What is the filing rate?", record)
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert len(result.violations) == 1


def test_record_without_confirmed_keep_answer_passes() -> None:
    """Single-turn record where keep_answer has confirm=False is fine."""
    record = AnswerRecord(
        question_id="q2",
        answerer="test",
        final_text="Previewing the answer.",
        tool_calls=[ToolCall(name="keep_answer", arguments={"confirm": False})],
    )
    evs = events_from_record("Show me.", record)
    result = check_events(evs)
    assert result.confirm_calls == 0
    assert result.violations == []


def test_record_no_tool_calls_passes() -> None:
    record = AnswerRecord(
        question_id="q3",
        answerer="test",
        final_text="Some text.",
    )
    evs = events_from_record("Question?", record)
    result = check_events(evs)
    assert result.confirm_calls == 0
    assert result.violations == []


def test_record_confirmed_keep_answer_exact_signature() -> None:
    """Exact AnswerRecord/ToolCall signature from the spec: 1 confirm, 1 violation."""
    rec = AnswerRecord(
        question_id="q",
        answerer="t",
        final_text="Saved.",
        tool_calls=[ToolCall(name="keep_answer", arguments={"confirm": True})],
    )
    result = check_events(events_from_record("Keep that answer", rec))
    assert result.confirm_calls == 1
    assert len(result.violations) == 1


# ---------------------------------------------------------------------------
# events_from_l1_messages
# ---------------------------------------------------------------------------


def _l1_msg(
    role: str,
    mtype: str,
    content: object,
) -> dict[str, object]:
    return {"role": role, "type": mtype, "content": content}


def test_l1_messages_happy_path() -> None:
    """L1 format with correct preview sequence passes."""
    messages = [
        _l1_msg("user", "text", "What is the rate?"),
        _l1_msg("assistant", "text", "The rate was 322. Shall I go ahead?"),
        _l1_msg("user", "text", "Yes, go ahead."),
        _l1_msg(
            "assistant",
            "tool_call",
            '{"name": "keep_answer", "args": {"confirm": true}}',
        ),
        _l1_msg("tool", "tool_response", "{}"),  # ignored
        _l1_msg("assistant", "text", "Done."),
    ]
    evs = events_from_l1_messages(messages)
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert result.violations == []


def test_l1_messages_dict_content_happy_path() -> None:
    """L1 tool_call with dict content (not JSON string) passes."""
    messages = [
        _l1_msg("assistant", "text", "Shall I go ahead?"),
        _l1_msg("user", "text", "Yes"),
        _l1_msg(
            "assistant",
            "tool_call",
            {"name": "keep_answer", "args": {"confirm": True}},
        ),
    ]
    evs = events_from_l1_messages(messages)
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert result.violations == []


def test_l1_messages_violation() -> None:
    """L1 format with no preview before confirm is a violation."""
    messages = [
        _l1_msg("user", "text", "Save it."),
        _l1_msg(
            "assistant",
            "tool_call",
            {"name": "keep_answer", "args": {"confirm": True}},
        ),
    ]
    evs = events_from_l1_messages(messages)
    result = check_events(evs)
    assert result.confirm_calls == 1
    assert len(result.violations) == 1


def test_l1_tool_response_ignored() -> None:
    """tool_response messages are skipped and do not create events."""
    messages = [
        _l1_msg("tool", "tool_response", "some result"),
        _l1_msg("tool", "tool_response", '{"status": "ok"}'),
    ]
    evs = events_from_l1_messages(messages)
    assert evs == []
