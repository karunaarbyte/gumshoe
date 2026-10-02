"""Deterministic label matching: the typed-text path, biased toward asking rather than guessing."""

from gumshoe.cases.core.text import normalise, tokens
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex

HEDGES = frozenset(
    {
        "not", "no", "never", "nor", "cannot", "innocent", "maybe", "perhaps", "possibly",
        "probably", "think", "guess", "suppose", "unless", "if", "might", "could",
        "doubt", "unlikely", "hardly", "impossible", "wrong", "false", "but", "except",
        "rather", "either", "instead", "else",
    }
)  # fmt: skip

# negative contractions once the apostrophe is gone ("wasn't" or "wasnt")
CONTRACTIONS = frozenset(
    {
        "wasnt", "isnt", "didnt", "dont", "doesnt", "cant", "wont", "couldnt", "wouldnt",
        "shouldnt", "arent", "hasnt", "havent",
    }
)  # fmt: skip


def candidate_forms(ix: CaseIndex, axis: Axis, candidate: str) -> tuple[str, ...]:
    """Everything a player may call this candidate: label, aliases and (suspects) display name."""
    if axis is Axis.WHO:
        s = ix.suspects[candidate]
        forms = (s.label, *s.aliases, s.display_name)
    elif axis is Axis.HOW:
        m = ix.methods[candidate]
        forms = (m.label, *m.aliases)
    else:
        v = ix.motives[candidate]
        forms = (v.label, *v.aliases)
    return tuple(f for f in forms if f.strip())


def hedged(text: str) -> bool:
    """A question, a negation or a hedge: never an affirmative accusation."""
    lowered = text.lower()
    if "?" in lowered or "n't" in lowered or "n’t" in lowered:
        return True
    return bool(set(normalise(text).split()) & (HEDGES | CONTRACTIONS))


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def match_label(ix: CaseIndex, axis: Axis, text: str) -> str | None:
    """The one candidate the text affirmatively names, or None (hedged, none or several match)."""
    if hedged(text):
        return None
    words = tokens(text)
    hits = [
        c
        for c in ix.candidates[axis]
        if any(_contains(words, tokens(form)) for form in candidate_forms(ix, axis, c))
    ]
    return hits[0] if len(hits) == 1 else None
