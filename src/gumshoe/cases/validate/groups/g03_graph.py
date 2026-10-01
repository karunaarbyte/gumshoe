"""Group 3: the fact and gate dependencies must form a DAG."""

from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue


def run(ctx: Ctx) -> list[Issue]:
    cycle = ctx.graph.cycle
    return [ctx.issue("DEPENDENCY_CYCLE", *cycle, facts=len(cycle))] if cycle else []
