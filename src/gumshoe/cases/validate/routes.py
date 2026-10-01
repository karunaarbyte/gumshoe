"""Routes to the truth: a `proves` fact, or the cheapest truthful rule-out per wrong candidate."""

from dataclasses import dataclass
from itertools import product

from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import Graph

MAX_ROUTES_PER_AXIS = 12  # bounds route enumeration and the combination search


@dataclass(frozen=True)
class Route:
    axis: Axis
    kind: str  # "proves" | "elimination"
    facts: frozenset[str]  # the route's facts together with all their ancestors


def _route_key(route: Route) -> tuple[int, str, list[str]]:
    return (len(route.facts), route.kind, sorted(route.facts))


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
    # Cap the proves routes only: a proves route always passes the gate (it is a lead), and the
    # elimination route is the one the cap must never drop.
    proves_routes = sorted((r for r in routes if r.kind == "proves"), key=_route_key)
    others = [r for r in routes if r.kind != "proves"]
    kept = proves_routes[: MAX_ROUTES_PER_AXIS - len(others)] + others
    return tuple(sorted(kept, key=_route_key))


@dataclass(frozen=True)
class Solution:
    size: int  # distinct facts in the cheapest union of route closures
    depth: int  # longest gating chain among them
    actions: int  # distinct sources among them
    facts: frozenset[str]


def best_solution(index: CaseIndex, graph: Graph, reach_facts: frozenset[str]) -> Solution | None:
    per_axis = [
        sorted(
            axis_routes(index, graph, reach_facts, axis),
            key=lambda r: (len(r.facts), sorted(r.facts)),
        )[:MAX_ROUTES_PER_AXIS]
        for axis in Axis
    ]
    if any(not routes for routes in per_axis):
        return None
    best: frozenset[str] | None = None
    best_key: tuple[int, tuple[str, ...]] | None = None
    for combo in product(*per_axis):
        union = frozenset().union(*(route.facts for route in combo))
        key = (len(union), tuple(sorted(union)))
        if best_key is None or key < best_key:
            best, best_key = union, key
    assert best is not None
    return Solution(
        size=len(best),
        depth=max(graph.depth[f] for f in best),
        actions=len({index.facts[f].source for f in best}),
        facts=best,
    )
