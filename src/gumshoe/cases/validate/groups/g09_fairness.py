"""Group 9: tells that would let a player guess the culprit from the shape of the case."""

from gumshoe.cases.model.entities import Fact
from gumshoe.cases.model.enums import Axis, EffectKind, SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.lies import valid_exposers
from gumshoe.cases.validate.report import Issue

_DECISIVE = (EffectKind.RULES_OUT, EffectKind.PROVES)


def owner(index: CaseIndex, fact: Fact) -> str | None:
    """The suspect a fact belongs to: its who-effect, else its record subject, else its speaker."""
    who = {e.candidate for e in fact.effects if e.axis is Axis.WHO}
    if len(who) == 1:
        return next(iter(who))
    if fact.source.kind is SourceKind.RECORD and fact.source.subject in index.suspects:
        return fact.source.subject
    return fact.speaker if fact.speaker in index.suspects else None


def _is_unique_extreme(values: dict[str, int], who: str) -> bool:
    if who not in values or len(values) < 3:
        return False
    others = [v for s, v in values.items() if s != who]
    return values[who] > max(others) or values[who] < min(others)


def run(ctx: Ctx) -> list[Issue]:
    case, ix, graph, reach = ctx.case, ctx.index, ctx.graph, ctx.reach
    out: list[Issue] = []
    suspects = [s.id for s in case.suspects]
    tolerance = case.spec.fairness_tolerance

    owned = dict.fromkeys(suspects, 0)
    for f in case.facts:
        o = owner(ix, f)
        if o in owned:
            owned[o] += 1
    lies = {s: sum(1 for f in case.facts if not f.truthful and f.speaker == s) for s in suspects}
    exposures = dict.fromkeys(suspects, 0)
    for lie in case.facts:
        if lie.truthful:
            continue
        for who in {owner(ix, e) for e in valid_exposers(ix, graph, reach.facts, lie)}:
            if who in exposures:
                exposures[who] += 1

    features = {"FACTS_UNEVEN": owned, "LIES_UNEVEN": lies, "EXPOSURES_UNEVEN": exposures}
    for code, values in features.items():
        if values and max(values.values()) - min(values.values()) > tolerance:
            out.append(
                ctx.issue(code, *sorted(values), spread=max(values.values()) - min(values.values()))
            )
    for code, values in features.items():
        if _is_unique_extreme(values, case.truth.who):
            out.append(
                ctx.issue("CULPRIT_UNIQUE_EXTREME", case.truth.who, axis=Axis.WHO, feature=code)
            )

    for axis in Axis:
        shapes: dict[str, tuple[tuple[str, str], ...]] = {}
        for cand in ix.candidates[axis]:
            entries = [
                (f.source.kind.value, "decisive" if e.kind in _DECISIVE else "supports")
                for f in case.facts
                if f.truthful
                for e in f.effects
                if e.axis is axis and e.candidate == cand
            ]
            shapes[cand] = tuple(sorted(entries))
        if len(set(shapes.values())) > 1:
            out.append(ctx.issue("SHAPE_MISMATCH", axis.value, axis=axis))

        depths: dict[str, int] = {}
        for cand in ix.candidates[axis]:
            found = [
                graph.depth[f.id]
                for f in case.facts
                if f.truthful
                and f.id in reach.facts
                and f.id in graph.depth
                and any(
                    e.axis is axis and e.candidate == cand and e.kind in _DECISIVE
                    for e in f.effects
                )
            ]
            if found:
                depths[cand] = min(found)
        truth = ix.truth(axis)
        if _is_unique_extreme(depths, truth):
            out.append(ctx.issue("TRUTH_DEPTH_EXTREME", truth, axis=axis))
    return out
