"""Group 5: every lie must be catchable by evidence the player can reach without needing the lie."""

from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.lies import exposer_problem, valid_exposers
from gumshoe.cases.validate.report import Issue


def run(ctx: Ctx) -> list[Issue]:
    ix, graph, reach = ctx.index, ctx.graph, ctx.reach
    out: list[Issue] = []
    for lie in ctx.case.facts:
        if lie.truthful:
            continue
        if lie.claim is None:
            out.append(ctx.issue("LIE_NO_CLAIM", lie.id))
        if lie.speaker is None:
            out.append(ctx.issue("LIE_NO_SPEAKER", lie.id))
        for exposer_id in lie.exposed_by:  # a lie never counts as an exposer, valid ones or not
            exposer = ix.facts.get(exposer_id)
            if exposer_id == lie.id or (exposer is not None and not exposer.truthful):
                out.append(ctx.issue("EXPOSER_IS_LIE", lie.id, exposer_id))
        valid = valid_exposers(ix, graph, reach.facts, lie)
        if valid:
            if lie.exposure_hook is None or lie.exposure_hook not in {e.source for e in valid}:
                out.append(ctx.issue("HOOK_MISMATCH", lie.id))
            continue
        if not lie.exposed_by:
            out.append(ctx.issue("EXPOSER_MISSING", lie.id))
            continue
        for exposer_id in lie.exposed_by:
            exposer = ix.facts.get(exposer_id)
            if exposer is None:
                continue
            problem = exposer_problem(ix, graph, reach.facts, lie, exposer)
            if problem is not None and problem != "EXPOSER_IS_LIE":
                out.append(ctx.issue(problem, lie.id, exposer.id))
    return out
