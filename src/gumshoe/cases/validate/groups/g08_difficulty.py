"""Group 8: how hard is the case, and does it survive losing any single fact?"""

from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.rules import gate
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Issue
from gumshoe.cases.validate.routes import axis_routes, best_solution


def _axis_ok(ctx: Ctx, reach_facts: frozenset[str], axis: Axis) -> bool:
    ix = ctx.index
    truth = ix.truth(axis)
    ruled_out = any(
        ix.facts[f].truthful
        and any(
            e.axis is axis and e.candidate == truth and e.kind is EffectKind.RULES_OUT
            for e in ix.facts[f].effects
        )
        for f in reach_facts
    )
    if ruled_out:
        return False
    routes = axis_routes(ix, ctx.graph, reach_facts, axis)
    return any(gate.permission(ix, route.facts, axis, truth).allowed for route in routes)


def run(ctx: Ctx) -> list[Issue]:
    case, ix, graph, reach = ctx.case, ctx.index, ctx.graph, ctx.reach
    limits = case.spec.limits
    out: list[Issue] = []

    best = best_solution(ix, graph, reach.facts)
    if best is not None:
        if not limits.solution_min <= best.size <= limits.solution_max:
            out.append(
                ctx.issue(
                    "SOLUTION_SIZE_RANGE",
                    "solution",
                    size=best.size,
                    min=limits.solution_min,
                    max=limits.solution_max,
                )
            )
        if not limits.depth_min <= best.depth <= limits.depth_max:
            out.append(
                ctx.issue(
                    "DEPTH_RANGE",
                    "solution",
                    depth=best.depth,
                    min=limits.depth_min,
                    max=limits.depth_max,
                )
            )
        if not limits.actions_min <= best.actions <= limits.actions_max:
            out.append(
                ctx.issue(
                    "ACTIONS_RANGE",
                    "solution",
                    actions=best.actions,
                    min=limits.actions_min,
                    max=limits.actions_max,
                )
            )

    total = len(case.facts)
    decisive = sum(
        1 for f in case.facts if f.truthful and any(e.kind is EffectKind.PROVES for e in f.effects)
    )
    if total and decisive * 100 > limits.decisive_pct_max * total:
        out.append(ctx.issue("DECISIVE_RATIO", "facts", decisive=decisive, total=total))

    for fact in case.facts:
        if fact.id in case.start.facts:
            continue
        remaining = compute_reach(ix, removed=frozenset({fact.id})).facts
        for axis in Axis:
            if not _axis_ok(ctx, remaining, axis):
                out.append(ctx.issue("SINGLE_POINT_OF_FAILURE", fact.id, axis=axis))
    return out
