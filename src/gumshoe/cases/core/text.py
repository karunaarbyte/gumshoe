"""Deterministic text normalisation: no locale, no dictionaries, no models."""

import unicodedata

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "and",
        "or",
        "from",
        "his",
        "her",
        "their",
        "is",
        "was",
        "were",
        "be",
        "it",
        "that",
        "this",
    }
)

_SUFFIXES = ("ing", "edly", "ed", "ly", "s")
_NO_DOUBLE_TRIM = "aeioulsz"


def normalise(text: str) -> str:
    """NFC, lowercase, punctuation to spaces, whitespace collapsed."""
    lowered = unicodedata.normalize("NFC", text).lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in lowered).split())


def stem(word: str) -> str:
    """A small, deterministic suffix stripper (not linguistically perfect, pinned by tests)."""
    base = word
    for suffix in _SUFFIXES:
        if base.endswith(suffix) and len(base) - len(suffix) >= 3:
            base = base[: -len(suffix)]
            break
    if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in _NO_DOUBLE_TRIM:
        base = base[:-1]
    if base.endswith("e") and len(base) > 4:
        base = base[:-1]
    return base


def tokens(text: str) -> tuple[str, ...]:
    return tuple(stem(word) for word in normalise(text).split() if word not in STOPWORDS)
