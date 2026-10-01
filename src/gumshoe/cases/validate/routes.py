"""Routes to the truth: a `proves` fact, or the cheapest truthful rule-out per wrong candidate."""

from dataclasses import dataclass

from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import Graph


@dataclass(frozen=True)
class Route:
    axis: Axis
    kind: str  # "proves" | "elimination"
    facts: frozenset[str]  # the route's facts together with all their ancestors


def axis_routes(
    index: CaseIndex, graph: Graph, reach_facts: frozenset[str], axis: Axis
) -> tuple[Route, ...]:
    truth = index.truth(axis)
    truthful = [
        index.facts[f] for f in sorted(reach_facts) if index.facts[f].truthful and f in graph.anc
    ]
    routes: list[Route] = []
    for fact in truthful:
        if any(
            e.axis is axis and e.candidate == truth and e.kind is EffectKind.PROVES
            for e in fact.effects
        ):
            routes.append(Route(axis, "proves", frozenset({fact.id}) | graph.anc[fact.id]))

    wrong = [c for c in index.candidates[axis] if c != truth]
    union: set[str] = set()
    complete = bool(wrong)
    for cand in wrong:
        options = [
            f
            for f in truthful
            if any(
                e.axis is axis and e.candidate == cand and e.kind is EffectKind.RULES_OUT
                for e in f.effects
            )
        ]
        if not options:
            complete = False
            break
        best = min(options, key=lambda f: (len(graph.anc[f.id]), f.id))
        union |= {best.id} | graph.anc[best.id]
    if complete:
        routes.append(Route(axis, "elimination", frozenset(union)))
    return tuple(routes)
