"""``keep_answer``'s preview check (ADR 0013).

A client that can't be asked by elicitation confirms a write in two calls:
``confirm=false`` returns a preview, ``confirm=true`` writes. On its own that
lets an agent skip the user: after a refused save it could resend restated
text with ``confirm=true`` and no new "Shall I go ahead?". So the preview call
returns a ``preview_id`` bound to a digest of what would be written (answer
text, option, asker, citations and the inquiry target), and the confirming
call must pass a matching one. Each id works once, whatever the outcome, so a
retry after ``written: false`` needs a new preview. Previews live in the desk
store, so they survive a server restarted between calls.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Sequence

from courts_analyst.core.desk import text as desk_text
from courts_analyst.core.desk.gate import _PLAIN
from courts_analyst.core.desk.models import Actor, CitationIn, InquiryTarget, Option
from courts_analyst.core.desk.store import DeskStore

PREVIEW_REQUIRED = (
    "Not saved: this call has no matching preview. Show the user a preview and "
    "ask 'Shall I go ahead?' first: call keep_answer with confirm=false for the "
    "exact answer you want to save, describe it to the user, and only after "
    "they say yes call again with confirm=true and the preview_id it returned. "
    "A preview_id works once, and only for the answer, option, asker and "
    "citations it was issued for."
)


_QUOTES = str.maketrans(
    dict.fromkeys("\u2018\u2019\u201a\u201b", "'")
    | dict.fromkeys("\u201c\u201d\u201e\u201f", '"')
)


def _canonical(text: str) -> str:
    """The answer as compared: NFKC, typographic dashes and quotes made plain,
    and no whitespace at all. A model re-emitting the same answer may write
    "FY\u202f2020" for "FY2020" or "JFF\u20112025" for "JFF-2025" (seen in
    the wxO desk runs); every word and number still has to match."""
    plain = desk_text.clean(text).translate(_PLAIN).translate(_QUOTES)
    return "".join(plain.split())


def digest(
    actor: Actor,
    option: Option,
    answer_text: str,
    citations: Sequence[CitationIn],
    inquiry: InquiryTarget | None,
) -> str:
    """What the user is asked to confirm. Whitespace, typographic dashes and
    quotes, and citation order don't matter; any other change to the text or
    a figure does."""
    payload = {
        "asker": [actor.account_id, actor.role],
        "option": option,
        "answer": _canonical(answer_text),
        "citations": sorted(
            [c.measure, c.court, c.fiscal_year, c.edition, float(c.value)]
            for c in citations
        ),
        "inquiry": (
            None
            if inquiry is None
            else [inquiry.measure, inquiry.court, inquiry.fiscal_year]
        ),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(
    store: DeskStore,
    actor: Actor,
    option: Option,
    answer_text: str,
    citations: Sequence[CitationIn],
    inquiry: InquiryTarget | None,
) -> str:
    """Record a preview and return its id."""
    preview_id = "pv_" + secrets.token_hex(5)
    store.add_preview(
        preview_id,
        actor.account_id,
        digest(actor, option, answer_text, citations, inquiry),
    )
    return preview_id


def redeem(
    store: DeskStore,
    actor: Actor,
    preview_id: str | None,
    option: Option,
    answer_text: str,
    citations: Sequence[CitationIn],
    inquiry: InquiryTarget | None,
    idempotency_key: str | None = None,
) -> bool:
    """Whether a ``confirm=true`` call may go ahead. Uses up the preview. A
    retry with an idempotency key that already wrote replays the first result,
    so it needs no new preview."""
    if store.remembered(actor.account_id, "submit_option", idempotency_key):
        return True
    if not preview_id:
        return False
    taken = store.take_preview(preview_id)
    return taken == (
        actor.account_id,
        digest(actor, option, answer_text, citations, inquiry),
    )
