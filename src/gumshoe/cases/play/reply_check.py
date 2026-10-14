"""reply_check: does a persona reply bring up a candidate the player has not met?

Free, deterministic, pass/fail plus a count per category. It flags any distinctive token of a
candidate (any axis) that the reply uses but that appears in none of: the player's own text,
the case brief, the held fact texts, the statements this suspect can speak right now, or the
small-talk words.

With the pack, the candidates are the pack's whole method and motive vocabulary, not just this
case's: a word of a method the case left out is flagged exactly like a word of one it holds, so
the check cannot be used to learn which methods and motives are in play. Words are compared with
`gate_tokens` (compatibility forms, zero-width characters, look-alike letters, hyphenated and
spelled-out words and a few more endings are all seen through).

Note: WHO-axis violations cannot fire in practice, because suspect names and roles are always
part of the brief and so always allowed.
"""

from gumshoe.cases.core.text import gate_tokens
from gumshoe.cases.model.entities import SourceRef
from gumshoe.cases.model.enums import Axis, SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.play.engine import available_facts
from gumshoe.cases.play.labels import typed_forms
from gumshoe.cases.play.state import PlayState
from gumshoe.cases.play.views import ReplyCheck, ReplyViolation


def _token_set(forms: tuple[str, ...]) -> frozenset[str]:
    return frozenset(t for form in forms if form.strip() for t in gate_tokens(form))


def _vocabulary(ix: CaseIndex, pack: Pack | None) -> dict[tuple[Axis, str], frozenset[str]]:
    """Token sets per item: every case candidate and, with the pack, every pack method and
    motive the case left out (a candidate made from a pack entry is that entry, once)."""
    items = {
        (axis, c): _token_set(typed_forms(ix, axis, c))
        for axis in Axis
        for c in ix.candidates[axis]
    }
    if pack is not None:
        in_case = {(Axis.HOW, m.type) for m in ix.case.methods}
        in_case |= {(Axis.WHY, v.type) for v in ix.case.motives}
        for axis, defs in ((Axis.HOW, pack.method_defs), (Axis.WHY, pack.motive_defs)):
            for d in defs:
                if (axis, d.key) not in in_case:
                    items[(axis, f"pack:{d.key}")] = _token_set((d.label, *d.aliases))
    return items


def _distinctive(
    items: dict[tuple[Axis, str], frozenset[str]],
) -> dict[tuple[Axis, str], frozenset[str]]:
    """Per item: its tokens minus any token another item also has."""
    out: dict[tuple[Axis, str], frozenset[str]] = {}
    for key, toks in items.items():
        others: frozenset[str] = frozenset().union(*(t for k, t in items.items() if k != key))
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
    return frozenset(t for text in texts for t in gate_tokens(text))


def reply_check(
    ix: CaseIndex,
    state: PlayState,
    suspect_id: str,
    player_text: str,
    reply: str,
    pack: Pack | None = None,
) -> ReplyCheck:
    allowed = _allowed_tokens(ix, state, suspect_id, player_text)
    used = gate_tokens(reply)
    counts: dict[str, int] = {}
    for (axis, _item), toks in _distinctive(_vocabulary(ix, pack)).items():
        if (toks & used) - allowed:
            counts[axis.value] = counts.get(axis.value, 0) + 1
    violations = tuple(ReplyViolation(category=c, count=n) for c, n in sorted(counts.items()))
    return ReplyCheck(ok=not violations, violations=violations)
