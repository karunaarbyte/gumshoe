"""Group 6: per axis, the truthful facts must single out the truth and give a route to it."""

from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.rules import gate
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue
from gumshoe.cases.validate.routes import axis_routes


def _route_passes_gate(ctx: Ctx, route_facts: frozenset[str], axis: Axis, truth: str) -> bool:
    """The shared gate must allow naming the truth with just the route held, and with every
    reachable lie held on top (extra facts never take permission away)."""
    ix = ctx.index
    lies = frozenset(f for f in ctx.reach.facts if not ix.facts[f].truthful)
    return (
        gate.permission(ix, route_facts, axis, truth).allowed
        and gate.permission(ix, route_facts | lies, axis, truth).allowed
    )


def run(ctx: Ctx) -> list[Issue]:
    ix, graph, reach = ctx.index, ctx.graph, ctx.reach
    out: list[Issue] = []
    truthful = [ix.facts[f] for f in sorted(reach.facts) if ix.facts[f].truthful]
    for axis in Axis:
        truth = ix.truth(axis)
        ruled: dict[str, list[str]] = {}
        for fact in truthful:
            for e in fact.effects:
                if e.axis is axis and e.kind is EffectKind.RULES_OUT:
                    ruled.setdefault(e.candidate, []).append(fact.id)
        if truth in ruled:
            out.append(ctx.issue("TRUTH_RULED_OUT", *ruled[truth], axis=axis))
        for cand in ix.candidates[axis]:
            if cand != truth and cand not in ruled:
                out.append(ctx.issue("WRONG_SURVIVES", cand, axis=axis))

        proves = [
            f
            for f in truthful
            if any(
                e.axis is axis and e.candidate == truth and e.kind is EffectKind.PROVES
                for e in f.effects
            )
        ]
        support_sources = {
            f.source
            for f in truthful
            if any(
                e.axis is axis and e.candidate == truth and e.kind is EffectKind.SUPPORTS
                for e in f.effects
            )
        }
        if not proves and len(support_sources) < 2:
            out.append(ctx.issue("NO_POSITIVE_EVIDENCE", truth, axis=axis))
        routes = axis_routes(ix, graph, reach.facts, axis)
        if not routes:
            out.append(ctx.issue("NO_ROUTE", truth, axis=axis, reason="none"))
        elif not any(_route_passes_gate(ctx, route.facts, axis, truth) for route in routes):
            out.append(ctx.issue("NO_ROUTE", truth, axis=axis, reason="gate"))
    return out
