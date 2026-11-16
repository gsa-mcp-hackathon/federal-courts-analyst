"""Claims scorer: mention checks are insensitive to Unicode typography."""

from __future__ import annotations

from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.schema import Claim
from courts_analyst.evaluation.scoring.claims import check_claim


def _rec(text: str) -> AnswerRecord:
    return AnswerRecord.model_validate(
        {"question_id": "q", "answerer": "t", "final_text": text}
    )


def _mentions(phrase: str) -> Claim:
    return Claim.model_validate({"id": "c", "kind": "mentions", "all": [phrase]})


def test_mentions_ascii_hyphen_passes() -> None:
    """Baseline: plain ASCII hyphen in both claim and text."""
    assert check_claim(_mentions("JB-2017"), _rec("See JB-2017 for details."))


def test_mentions_unicode_nbhyphen_in_text_passes() -> None:
    """U+2011 non-breaking hyphen in the answer text must match 'JB-2017' claim."""
    assert check_claim(_mentions("JB-2017"), _rec("See JB\u20112017 for details."))


def test_mentions_unicode_nbhyphen_in_both_passes() -> None:
    """U+2011 in both claim and text."""
    assert check_claim(_mentions("JB\u20112017"), _rec("See JB\u20112017 for details."))


def test_mentions_unicode_nbhyphen_in_claim_passes() -> None:
    """U+2011 in the claim phrase, ASCII hyphen in the text."""
    assert check_claim(_mentions("JB\u20112017"), _rec("See JB-2017 for details."))


def test_mentions_nbsp_in_text_passes() -> None:
    """U+00A0 no-break space in answer text must match plain-space claim phrase."""
    assert check_claim(
        _mentions("Northern District of Florida"),
        _rec("Filed in Northern\u00a0District\u00a0of\u00a0Florida."),
    )


def test_mentions_nbsp_in_claim_passes() -> None:
    """U+00A0 no-break space in the claim phrase, plain space in the text."""
    assert check_claim(
        _mentions("Northern\u00a0District\u00a0of\u00a0Florida"),
        _rec("Filed in Northern District of Florida."),
    )


def test_direct_filing_claim_accepts_hyphenated_directly() -> None:
    """wxO runs 20261113T200423Z and 20261113T201533Z wrote "Directly-filed MDL
    cases" (also with U+2011); the bank's claim must accept that spelling."""
    from courts_analyst.evaluation.bank import load_bank

    item = next(i for i in load_bank() if i.id == "why-fy2020-civil-filings-jump")
    claim = next(c for c in item.claims if c.id == "notes_direct_filing")
    for text in ("**Directly-filed** MDL cases", "Directly‑filed MDL cases"):
        assert check_claim(claim, _rec(text))


def test_mentions_ignores_markdown_emphasis() -> None:
    """The wxO agent bolds numbers: "**7** additional" says "7 additional"."""
    text = "The Conference recommended **7** additional judgeships (JC‑2025)."
    assert check_claim(_mentions("7 additional"), _rec(text))
    assert check_claim(_mentions("7 additional"), _rec("recommended `7` additional"))


def test_not_mentions_sees_through_markdown_emphasis() -> None:
    claim = Claim.model_validate(
        {"id": "c", "kind": "not_mentions", "any": ["I recommend"]}
    )
    assert not check_claim(claim, _rec("**I** recommend adding judgeships."))
