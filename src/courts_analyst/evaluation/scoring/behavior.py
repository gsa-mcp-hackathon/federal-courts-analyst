"""Did the answer answer, ask for clarification, or decline?

A declared behaviour wins. Otherwise structured signals from our tools
(``status: needs_clarification`` or ``declined``) decide, then phrases in the
final text. The phrase lists are deliberately conservative: a false
"declined" costs an answer its credit, so only unambiguous wording counts.
"""

from __future__ import annotations

import re

from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.schema import Behavior

_DECLINE = re.compile(
    r"\b(?:I\s+(?:can(?:no|')t|won't|will\s+not|am\s+not\s+able\s+to|'m\s+not\s+able\s+to"
    r"|must\s+decline|decline)|(?:this|the)\s+server\s+(?:does\s+not|doesn't|won't|will\s+not)"
    r"\s+(?:rank|provide|profile|return|identify|release|share)"
    r"|not\s+(?:able|permitted|allowed)\s+to\s+(?:rank|profile|identify|provide)"
    r"|(?:is|are)\s+(?:outside|out\s+of)\s+(?:the\s+)?scope|no\s+data\s+(?:for|on|before|after)"
    r"|(?:isn't|is\s+not|aren't|are\s+not)\s+(?:covered|available|in\s+(?:the|our)\s+data)"
    r"|too\s+few\s+cases|(?:result|figure|count)\s+(?:is|was)\s+suppressed"
    r"|fewer\s+than\s+\d+\s+cases)",
    re.I,
)
_CLARIFY = re.compile(
    r"(?:do\s+you\s+mean|did\s+you\s+mean|could\s+you\s+(?:clarify|specify|confirm)"
    r"|can\s+you\s+(?:clarify|specify|confirm)|which\s+(?:one|figure|edition|measure|of\s+these)"
    r"\s+(?:do|would)\s+you|would\s+you\s+like\s+(?:the|me\s+to\s+use)|please\s+(?:clarify|specify|confirm))",
    re.I,
)


def infer_behavior(record: AnswerRecord) -> Behavior:
    if record.behavior is not None:
        return record.behavior
    statuses = {str(o.get("status")) for o in record.structured_outputs}
    final_asks = bool(_CLARIFY.search(record.final_text))
    if "needs_clarification" in statuses and (final_asks or not record.final_text):
        return "clarify"
    if "declined" in statuses and not record.final_text:
        return "decline"
    if _CLARIFY.search(record.final_text) and record.final_text.rstrip().endswith("?"):
        return "clarify"
    if _DECLINE.search(record.final_text):
        return "decline"
    if "declined" in statuses:
        return "decline"
    return "answer"
