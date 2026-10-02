"""reply_check: does a persona reply bring up a candidate the player has not met?

Free, deterministic, pass/fail plus a count per category. It flags any distinctive token of a
candidate (any axis) that the reply uses but that appears in none of: the player's own text,
the case brief, the held fact texts, the statements this suspect can speak right now, or the
small-talk words.

Note: WHO-axis violations cannot fire in practice, because suspect names and roles are always
part of the brief and so always allowed.
"""

from gumshoe.cases.core.text import tokens
from gumshoe.cases.model.entities import SourceRef
from gumshoe.cases.model.enums import Axis, SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.engine import available_facts
from gumshoe.cases.play.labels import typed_forms
from gumshoe.cases.play.state import PlayState
from gumshoe.cases.play.views import ReplyCheck, ReplyViolation


def _distinctive(ix: CaseIndex) -> dict[tuple[Axis, str], frozenset[str]]:
    """Per candidate: its label/alias tokens minus any token another candidate also has."""
    own = {
        (axis, c): frozenset(t for form in typed_forms(ix, axis, c) for t in tokens(form))
        for axis in Axis
        for c in ix.candidates[axis]
    }
    out: dict[tuple[Axis, str], frozenset[str]] = {}
    for key, toks in own.items():
        others: frozenset[str] = frozenset().union(*(t for k, t in own.items() if k != key))
        out[key] = toks - others
    return out


def _allowed_tokens(
    ix: CaseIndex, state: PlayState, suspect_id: str, player_text: str
) -> frozenset[str]:
    case = ix.case
    held = state.held
    texts = [player_text, case.intro, " ".join(case.smalltalk_allow)]
    texts += [f"{loc.name} {loc.description}" for loc in case.locations]
    texts += [f"{s.display_name} {s.description}" for s in case.suspects]
    texts += [f.text for f in case.facts if f.id in held]
    source = SourceRef(kind=SourceKind.INTERROGATE, target=suspect_id)
    texts += [f.text for f in available_facts(ix, held, source)]
    return frozenset(t for text in texts for t in tokens(text))


def reply_check(
    ix: CaseIndex, state: PlayState, suspect_id: str, player_text: str, reply: str
) -> ReplyCheck:
    allowed = _allowed_tokens(ix, state, suspect_id, player_text)
    used = frozenset(tokens(reply))
    counts: dict[str, int] = {}
    for (axis, _candidate), toks in _distinctive(ix).items():
        if (toks & used) - allowed:
            counts[axis.value] = counts.get(axis.value, 0) + 1
    violations = tuple(ReplyViolation(category=c, count=n) for c, n in sorted(counts.items()))
    return ReplyCheck(ok=not violations, violations=violations)
