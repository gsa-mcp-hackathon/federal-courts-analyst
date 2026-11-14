"""Deterministic checker for the request-desk preview rule.

Rule: every ``keep_answer`` tool call whose arguments have ``confirm`` set to
``True`` (or the string ``'true'``) must be preceded – after the previous
confirmed ``keep_answer`` – by:

1. An **assistant** text turn that contains a question starting with
   ``'Shall I go ahead'`` (case-insensitive, after :func:`normalize_quotes`),
   matched by the regex ``r'shall i go ahead[^.!?]*\\?'``.
2. A **user** text turn that starts with one of the affirmative words:
   ``yes``, ``yeah``, ``yep``, ``sure``, ``ok``, ``okay``, ``go ahead``,
   ``please do``, ``do it``, ``confirm`` (case-insensitive).

Every confirmed call needs its own preview and yes; they may not be shared
across two confirmed calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.scoring.behavior import normalize_quotes

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_YES_PREFIXES = (
    "yes",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "go ahead",
    "please do",
    "do it",
    "confirm",
)


class Event(BaseModel, frozen=True):
    """A single turn or tool call in a conversation."""

    kind: Literal["user", "assistant", "tool_call"]
    text: str = ""
    name: str = ""
    args: dict[str, Any] = {}


class PreviewResult(BaseModel, frozen=True):
    """Outcome of a preview-rule check."""

    confirm_calls: int
    violations: list[str]


# ---------------------------------------------------------------------------
# Core checker
# ---------------------------------------------------------------------------


def _is_confirmed(args: dict[str, Any]) -> bool:
    """Return True when the tool call's ``confirm`` argument is truthy."""
    v = args.get("confirm")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() == "true"
    return False


_PREVIEW_RE = re.compile(r"shall i go ahead[^.!?]*\?", re.IGNORECASE)


def _has_preview(text: str) -> bool:
    return bool(_PREVIEW_RE.search(normalize_quotes(text)))


def _is_yes(text: str) -> bool:
    lowered = normalize_quotes(text).lower().strip()
    return any(lowered.startswith(p) for p in _YES_PREFIXES)


def check_events(events: list[Event]) -> PreviewResult:
    """Check *events* for preview-rule violations.

    Returns a :class:`PreviewResult` with the number of confirmed
    ``keep_answer`` calls found and a (possibly empty) list of violation
    descriptions.
    """
    violations: list[str] = []
    confirm_calls = 0

    # State between confirmed calls: reset after each confirmed keep_answer.
    saw_preview = False
    saw_yes = False

    for idx, event in enumerate(events):
        if event.kind != "tool_call" or event.name != "keep_answer":
            # Track assistant preview and user yes in the window between
            # consecutive confirmed keep_answer calls.
            if event.kind == "assistant" and event.text:
                if _has_preview(event.text):
                    saw_preview = True
                    saw_yes = False  # yes must come *after* the preview
            elif (
                event.kind == "user"
                and event.text
                and saw_preview
                and _is_yes(event.text)
            ):
                saw_yes = True
            continue

        # It's a keep_answer tool call.
        if not _is_confirmed(event.args):
            continue

        confirm_calls += 1
        label = f"keep_answer #{confirm_calls} (event index {idx})"

        if not saw_preview:
            violations.append(f"{label}: no 'Shall I go ahead?' preview before confirm")
        elif not saw_yes:
            violations.append(f"{label}: no user yes after preview before confirm")

        # Reset window for the next confirmed call.
        saw_preview = False
        saw_yes = False

    return PreviewResult(confirm_calls=confirm_calls, violations=violations)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def events_from_record(question: str, record: AnswerRecord) -> list[Event]:
    """Build a flat event list from a *single-turn* evaluation record.

    Layout: user question → tool calls in order → final assistant text.
    Because this is single-turn, any confirmed ``keep_answer`` is a violation
    (there is no room for an assistant preview and a user yes).
    """
    evs: list[Event] = [Event(kind="user", text=question)]
    for tc in record.tool_calls:
        evs.append(Event(kind="tool_call", name=tc.name, args=tc.arguments))
    if record.final_text:
        evs.append(Event(kind="assistant", text=record.final_text))
    return evs


def events_from_l1_messages(messages: list[dict[str, Any]]) -> list[Event]:
    """Build a flat event list from a Layer-1 orchestrate messages file.

    Each message dict has ``role``, ``type`` and ``content``.

    * ``type == 'tool_call'``: ``content`` is a JSON string *or* dict with
      ``name`` and ``args``; produces a ``tool_call`` event.
    * ``type == 'tool_response'``: ignored.
    * Any other ``role == 'user'`` or ``role == 'assistant'`` message:
      ``content`` is treated as plain text; produces the matching text event.
    """
    evs: list[Event] = []
    for msg in messages:
        role: str = msg.get("role", "")
        mtype: str = msg.get("type", "")
        content = msg.get("content", "")

        if mtype == "tool_call":
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    parsed = {}
            else:
                parsed = content if isinstance(content, dict) else {}
            name: str = parsed.get("name", "")
            args: dict[str, Any] = parsed.get("args", {})
            evs.append(Event(kind="tool_call", name=name, args=args))
        elif mtype == "tool_response":
            continue
        elif role in ("user", "assistant"):
            text = content if isinstance(content, str) else str(content)
            evs.append(Event(kind=role, text=text))

    return evs


# ---------------------------------------------------------------------------
# File-level helpers used by the CLI
# ---------------------------------------------------------------------------


def _check_jsonl(path: Path) -> PreviewResult:
    """Check a run-records ``.jsonl`` file.

    Each row has ``question`` and ``record``.
    """
    all_violations: list[str] = []
    total_confirms = 0
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        question: str = obj.get("question", "")
        record = AnswerRecord.model_validate(obj["record"])
        evs = events_from_record(question, record)
        result = check_events(evs)
        total_confirms += result.confirm_calls
        for v in result.violations:
            all_violations.append(f"line {lineno}: {v}")
    return PreviewResult(confirm_calls=total_confirms, violations=all_violations)


def _check_messages_file(path: Path) -> PreviewResult:
    """Check a single ``*.messages.json`` Layer-1 messages file."""
    messages: list[dict[str, Any]] = json.loads(path.read_text())
    evs = events_from_l1_messages(messages)
    return check_events(evs)


def _check_l1_dir(directory: Path) -> PreviewResult:
    """Check all ``messages/*.messages.json`` files under *directory* recursively."""
    all_violations: list[str] = []
    total_confirms = 0
    for mfile in sorted(directory.rglob("messages/*.messages.json")):
        rel = mfile.relative_to(directory)
        result = _check_messages_file(mfile)
        total_confirms += result.confirm_calls
        for v in result.violations:
            all_violations.append(f"{rel}: {v}")
    return PreviewResult(confirm_calls=total_confirms, violations=all_violations)


def check_path(path: Path) -> PreviewResult:
    """Dispatch to the right checker based on whether *path* is a file or dir."""
    if path.is_dir():
        return _check_l1_dir(path)
    return _check_jsonl(path)
