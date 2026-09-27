"""Output PII scanner: no party name leaves the server.

Party names never enter the server's database (Phase 2 keeps them in a
separate Parquet file the server can't open). This scanner is the second
wall: every result is checked against an index of **hashed** party names
before it is returned, and a match withholds the whole result (fail closed).

The index (``pii_index.bin``, next to ``idb.duckdb``) is built by the IDB
pipeline. It holds 64-bit keyed BLAKE2b hashes of normalised party names,
never the names, plus a bitmap of hashed first words so most text is
skipped cheaply. Only names of two or more words are indexed: a bare
surname ("SMITH", most single-word entries) identifies no one and would flag
ordinary words. A match that also occurs in the server's own vocabulary
(court names, codebook labels, glossary, tool text) is not a leak: "UNITED
STATES" is both a party and a court name.

The hashes are not secret: anyone with the public IDB can compute them. They
keep a plain name list out of the image and the logs, which is the point.
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
import threading
from array import array
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Final

MAGIC: Final = b"FCAPII1\0"
BITMAP_LOG2: Final = 24
"""First-word bitmap size: 2^24 bits (2 MiB)."""
MAX_WORDS: Final = 8
"""Longest name indexed, in words (IDB name fields hold 30 characters)."""
_KEY: Final = b"federal-courts-analyst/pii/v1"
_NON_WORD = re.compile(r"[^A-Z0-9&]+")
_SEPARATORS = re.compile(r"[|·;\n]+")
_DROP_TAIL: Final = ("ET AL", "ETC", "ET AL ETC")


def normalize(text: str) -> list[str]:
    """Upper-case words, punctuation dropped: "3M Co., et al." → [3M, CO]."""
    words = _NON_WORD.sub(" ", text.upper().replace("'", "")).split()
    joined = " ".join(words)
    for tail in _DROP_TAIL:
        if joined.endswith(" " + tail):
            words = words[: -len(tail.split())]
            break
    return words


def _hash(phrase: str) -> int:
    digest = hashlib.blake2b(phrase.encode(), digest_size=8, key=_KEY).digest()
    return int.from_bytes(digest, "little")


def _bit(word: str) -> int:
    return _hash("\x00" + word) & ((1 << BITMAP_LOG2) - 1)


def indexable(words: list[str]) -> bool:
    """Two or more words with at least four letters between them."""
    return (
        2 <= len(words) <= MAX_WORDS and sum(c.isalpha() for c in "".join(words)) >= 4
    )


def build_index(names: Iterable[str | None], path: Path) -> int:
    """Write the hashed index of ``names`` to ``path``; return its size."""
    hashes: set[int] = set()
    bitmap = bytearray(1 << (BITMAP_LOG2 - 3))
    for name in names:
        if not name:
            continue
        words = normalize(name)
        if not indexable(words):
            continue
        hashes.add(_hash(" ".join(words)))
        b = _bit(words[0])
        bitmap[b >> 3] |= 1 << (b & 7)
    values = array("Q", sorted(hashes))
    if sys.byteorder != "little":
        values.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        fh.write(MAGIC + struct.pack("<BQ", BITMAP_LOG2, len(values)))
        fh.write(bitmap)
        fh.write(values.tobytes())
    tmp.replace(path)
    return len(values)


class PiiIndexError(Exception):
    """The index file is missing or unreadable."""


class PiiIndex:
    """The loaded index: a first-word bitmap and sorted 64-bit hashes."""

    def __init__(self, path: Path) -> None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise PiiIndexError(f"PII index not readable: {path.name}") from exc
        head = len(MAGIC) + 9
        if raw[: len(MAGIC)] != MAGIC:
            raise PiiIndexError("PII index has the wrong format")
        log2, n = struct.unpack("<BQ", raw[len(MAGIC) : head])
        size = 1 << (log2 - 3)
        if log2 != BITMAP_LOG2 or len(raw) != head + size + 8 * n:
            raise PiiIndexError("PII index is truncated or corrupt")
        self.bitmap = raw[head : head + size]
        self.hashes = array("Q")
        self.hashes.frombytes(raw[head + size :])
        if sys.byteorder != "little":
            self.hashes.byteswap()

    def __len__(self) -> int:
        return len(self.hashes)

    def _first_word(self, word: str) -> bool:
        b = _bit(word)
        return bool(self.bitmap[b >> 3] & (1 << (b & 7)))

    def _contains(self, phrase: str) -> bool:
        h = _hash(phrase)
        i = bisect_left(self.hashes, h)
        return i < len(self.hashes) and self.hashes[i] == h

    def matches(self, text: str) -> Iterator[str]:
        """Every indexed name that appears as a run of words in ``text``.

        A run never crosses a separator ("|", "·", ";", a line break): keys
        like "LA-E|Insurance" join two fields, not the words of one name."""
        for segment in _SEPARATORS.split(text):
            yield from self._matches(normalize(segment))

    def _matches(self, words: list[str]) -> Iterator[str]:
        for i, w in enumerate(words):
            if not self._first_word(w):
                continue
            for j in range(i + 2, min(len(words), i + MAX_WORDS) + 1):
                run = words[i:j]
                if indexable(run) and self._contains(" ".join(run)):
                    yield " ".join(run)


@cache
def vocabulary() -> str:
    """The server's own text, normalised: " WORD WORD … " for phrase lookup.

    Everything the server can say from fixed sources: the package's code and
    data files (court names, codebook labels, glossary, measures, tool
    descriptions, methodology). Loaded once.
    """
    root = resources.files("courts_analyst")
    parts: list[str] = []
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.iterdir():
            if child.is_dir():
                if child.name != "__pycache__":
                    stack.append(child)
            elif child.name.endswith((".py", ".yaml", ".md")):
                text = child.read_bytes().decode(errors="ignore")
                parts.append(" ".join(normalize(text)))
    return " " + " ".join(parts) + " "


def strings(obj: Any) -> Iterator[str]:
    """Every string value in a JSON-like object (keys are fixed names)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from strings(v)


class Scanner:
    """Finds party names in a result.

    ``extra_vocabulary`` is more of the server's own text (for example
    footnotes from the catalog). ``boundaries`` are phrases the server
    inserts into its sentences (court names and citations): each is treated
    as a separator, so "W.D. La. rose by 41" can't read as a name "LA ROSE".
    """

    def __init__(
        self,
        index: PiiIndex,
        extra_vocabulary: str = "",
        boundaries: Iterable[str] = (),
    ) -> None:
        self.index = index
        self.vocab = vocabulary() + " ".join(normalize(extra_vocabulary)) + " "
        phrases = sorted({b for b in boundaries if b}, key=len, reverse=True)
        self._boundary = (
            re.compile(
                r"(?<![A-Za-z])(?:" + "|".join(map(re.escape, phrases)) + r")(?![a-z])"
            )
            if phrases
            else None
        )

    def hits(self, payload: Any) -> list[str]:
        found = []
        for s in strings(payload):
            if self._boundary is not None:
                s = self._boundary.sub(" | ", s)
            for phrase in self.index.matches(s):
                if f" {phrase} " not in self.vocab:
                    found.append(phrase)
        return found


_lock = threading.Lock()
_cache: dict[tuple[Path, float], PiiIndex] = {}


def load_index(path: Path) -> PiiIndex:
    """The index at ``path``, cached until the file changes."""
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        raise PiiIndexError(f"PII index not found: {path.name}") from exc
    with _lock:
        key = (path, mtime)
        if key not in _cache:
            _cache.clear()
            _cache[key] = PiiIndex(path)
        return _cache[key]


def fingerprint(phrase: str) -> str:
    """A short hash of a matched phrase, for logs (never the phrase)."""
    return f"{_hash(phrase):016x}"[:12]
