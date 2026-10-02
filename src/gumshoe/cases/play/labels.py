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


def jev_forms(ix: CaseIndex, axis: Axis, candidate: str) -> tuple[str, ...]:
    """The label and aliases: the only text Jev sees for a candidate (spec)."""
    if axis is Axis.WHO:
        s = ix.suspects[candidate]
        forms = (s.label, *s.aliases)
    elif axis is Axis.HOW:
        m = ix.methods[candidate]
        forms = (m.label, *m.aliases)
    else:
        v = ix.motives[candidate]
        forms = (v.label, *v.aliases)
    return tuple(f for f in forms if f.strip())


def typed_forms(ix: CaseIndex, axis: Axis, candidate: str) -> tuple[str, ...]:
    """Everything a player may type for this candidate: the Jev forms and, for a suspect, the
    display name the game shows."""
    forms = jev_forms(ix, axis, candidate)
    if axis is Axis.WHO and ix.suspects[candidate].display_name.strip():
        forms = (*forms, ix.suspects[candidate].display_name)
    return forms


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
        if any(_contains(words, tokens(form)) for form in typed_forms(ix, axis, c))
    ]
    return hits[0] if len(hits) == 1 else None
