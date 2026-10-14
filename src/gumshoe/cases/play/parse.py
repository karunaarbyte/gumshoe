"""Turning the player's words into candidates through Jev: the question set and a pure reader.

Only play/ may import gumshoe.decider, and only its public types. No call is made here: the
agent loop sends `prompt.questions` through its own Decider and passes the option probabilities
to `interpret_probabilities`.
"""

import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.labels import jev_forms
from gumshoe.decider import ChoiceQuestion

TOP_MIN = 0.6  # the best option must be more likely than this ...
MARGIN_MIN = 0.25  # ... and ahead of the runner-up by more than this, else it is `unclear`

AXIS_PHRASE = {Axis.WHO: "culprit", Axis.HOW: "method", Axis.WHY: "motive"}
UNCLEAR_CRITERIA = (
    "The player does not clearly and affirmatively name exactly one of the other options for "
    "this point: a negation, a question, a hedge, a choice between several, or no accusation."
)


@dataclass(frozen=True)
class AccusationPrompt:
    state: str
    questions: dict[str, ChoiceQuestion]
    keys: dict[str, dict[str, str | None]]  # axis -> option letter -> candidate handle | None


def _criteria(ix: CaseIndex, axis: Axis, candidate: str) -> str:
    label, *others = jev_forms(ix, axis, candidate)
    extra = f" (also called: {', '.join(dict.fromkeys(others))})" if others else ""
    return f"The player affirmatively accuses this candidate: {label}{extra}."


def accusation_questions(
    ix: CaseIndex,
    handle_of: Callable[[str], str],
    n_accusations: int,
    player_text: str,
    allowed: Mapping[Axis, frozenset[str]] | None = None,
) -> AccusationPrompt:
    """Three choice questions, one per axis; option letters are shuffled deterministically from
    (case id, accusations so far) so the layout changes each attempt but replays exactly.
    With `allowed`, an axis offers only those candidates (plus unclear), so the prompt never
    names one the player may not; an axis with none is not asked, and reads as no pick."""
    questions: dict[str, ChoiceQuestion] = {}
    keys: dict[str, dict[str, str | None]] = {}
    for axis in Axis:
        pool = ix.candidates[axis] if allowed is None else allowed[axis]
        items: list[str | None] = [*(c for c in ix.candidates[axis] if c in pool), None]

        def shuffle_key(item: str | None, axis: Axis = axis) -> str:
            return domain_digest(
                "gumshoe.accusation.keys.v1",
                canonical_json([ix.case.id, n_accusations, axis.value, item]),
            )

        if len(items) < 2:
            continue  # nothing nameable on this axis: there is nothing to ask Jev
        ordered = sorted(items, key=shuffle_key)
        if len(ordered) > len(string.ascii_uppercase):
            raise ValueError("more options than option letters")
        criteria: dict[str, str] = {}
        keymap: dict[str, str | None] = {}
        for letter, item in zip(string.ascii_uppercase, ordered, strict=False):
            keymap[letter] = None if item is None else handle_of(item)
            criteria[letter] = UNCLEAR_CRITERIA if item is None else _criteria(ix, axis, item)
        questions[axis.value] = ChoiceQuestion(
            instructions=(
                f"Which {AXIS_PHRASE[axis]} does the player's message affirmatively accuse? "
                "Pick the unclear option for anything that is not a clear accusation."
            ),
            criteria=criteria,
        )
        keys[axis.value] = keymap
    return AccusationPrompt(state=f"The player said: {player_text}", questions=questions, keys=keys)


def _pick(keymap: dict[str, str | None], probabilities: Mapping[str, float]) -> str | None:
    ranked = sorted(probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return None
    top_key, top_p = ranked[0]
    second_p = ranked[1][1] if len(ranked) > 1 else 0.0
    if top_p <= TOP_MIN or top_p - second_p <= MARGIN_MIN:
        return None
    return keymap.get(top_key)


def interpret_probabilities(
    prompt: AccusationPrompt, probabilities: Mapping[str, Mapping[str, float]]
) -> dict[Axis, str | None]:
    """A part is a candidate only on a confident, clear win; everything else is None."""
    out: dict[Axis, str | None] = {}
    for axis in Axis:
        keymap = prompt.keys.get(axis.value)
        probs = probabilities.get(axis.value)
        out[axis] = _pick(keymap, probs) if keymap is not None and probs is not None else None
    return out
