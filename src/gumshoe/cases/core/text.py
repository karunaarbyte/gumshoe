"""Deterministic text normalisation: no locale, no dictionaries, no models."""

import re
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


# -- the leak gate (reply_check) --------------------------------------------------------------
# Stricter than `tokens`, and used only by the gate: the generator and the validator keep
# `normalise`, `stem` and `tokens`, so generated cases (and their saves) do not change.

# Letters from other scripts that look like Latin ones (a Cyrillic o in "poison" reads as o).
_LOOK_ALIKES = str.maketrans(
    {
        "\u0430": "a", "\u0432": "b", "\u0435": "e", "\u043a": "k", "\u043c": "m", "\u043d": "h",
        "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0442": "t", "\u0443": "y", "\u0445": "x",
        "\u0456": "i", "\u0458": "j", "\u0455": "s", "\u0501": "d",
        "\u03b1": "a", "\u03b2": "b", "\u03b5": "e", "\u03b9": "i", "\u03ba": "k", "\u03bd": "v",
        "\u03bf": "o", "\u03c1": "p", "\u03c4": "t", "\u03c5": "u", "\u03c7": "x",
    }
)  # fmt: skip
_HYPHENS = re.compile(r"\s*[-\u2010-\u2015\u2212]\s*")
# (ending, replacement, letters that must remain): agent nouns and adjectives `stem` keeps
_GATE_ENDINGS = (("ers", "", 6), ("er", "", 6), ("ous", "", 4), ("ful", "", 4), ("ves", "f", 3))


def _visible(text: str) -> str:
    """NFKC (full-width and other compatibility forms), with format characters (zero-width
    spaces and joiners, soft hyphens) removed."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf"
    )


def gate_normalise(text: str) -> str:
    """`normalise` for the leak gate: visible characters only, case folded, look-alike
    Cyrillic and Greek letters read as Latin, punctuation to spaces."""
    folded = _visible(text).casefold().translate(_LOOK_ALIKES)
    return " ".join("".join(ch if ch.isalnum() else " " for ch in folded).split())


def gate_stem(word: str) -> str:
    """`stem` after one more ending: poisoner, poisonous, blackmailer, fearful and knives meet
    poison, blackmail, fear and knife. Not linguistically perfect (vengeful still misses
    vengeance); pinned by tests."""
    for ending, replacement, keep in _GATE_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= keep:
            word = word[: -len(ending)] + replacement
            break
    return stem(word)


def _spelled_out(words: list[str]) -> list[str]:
    """Runs of two or more single letters, joined: "p o i s o n" gives "poison"."""
    joined: list[str] = []
    run: list[str] = []
    for word in [*words, ""]:
        if len(word) == 1:
            run.append(word)
            continue
        if len(run) >= 2:
            joined.append("".join(run))
        run = []
    return joined


def gate_tokens(text: str) -> frozenset[str]:
    """Every word a reader would see in the text, stemmed with `gate_stem`, stopwords dropped:
    the words themselves, the text with its hyphens closed up ("cross-bow", "p-o-i-s-o-n"), and
    spelled-out words ("P O I S O N")."""
    words = gate_normalise(text).split()
    closed = gate_normalise(_HYPHENS.sub("", _visible(text))).split()
    every = (*words, *closed, *_spelled_out(words))
    return frozenset(gate_stem(word) for word in every if word not in STOPWORDS)
