"""Shared helpers for the generator tests."""

from collections.abc import Callable, Mapping
from math import sqrt
from typing import Any

from gumshoe.cases.generate import facts, roster, timeline, truth
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, RosterOut, TimelineOut, TruthOut
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.tools.builtin import load_builtin_pack

PRESET_NAMES = ("short", "standard", "long")
SEEDS = range(200)
GOLDEN_SEEDS = (0, 1, 2, 3, 4)
Z_BONFERRONI = 3.29  # one-sided p = 0.0005 per test, about 0.005 over the ten statistical tests


def castle() -> Pack:
    return load_builtin_pack("castle")


def roster_of(ctx: GenContext) -> RosterOut:
    return roster.run(ctx, ctx.stream("roster"))


def truth_of(ctx: GenContext) -> tuple[RosterOut, TruthOut]:
    before = roster_of(ctx)
    return before, truth.run(ctx, ctx.stream("truth"), before)


def stages(ctx: GenContext) -> tuple[RosterOut, TruthOut, TimelineOut]:
    """The three structural stages, called directly (the fold in `structure.py` is tested apart)."""
    before, after = truth_of(ctx)
    return before, after, timeline.run(ctx, ctx.stream("timeline"), after)


def facts_of(ctx: GenContext, depth: int | None = None) -> tuple[TruthOut, TimelineOut, FactsOut]:
    """The truth, the timeline and the facts for a context; `depth` forces the gating depth."""
    _, after, tl = stages(ctx)
    return after, tl, facts.run(ctx, ctx.stream("facts"), after, tl, depth)


def chi2_critical(df: int, z: float = Z_BONFERRONI) -> float:
    """The chi-square quantile for z standard deviations (Wilson-Hilferty), no scipy needed."""
    return df * (1 - 2 / (9 * df) + z * sqrt(2 / (9 * df))) ** 3


def chi2_statistic[K](observed: Mapping[K, int], expected: Mapping[K, float]) -> float:
    """Pearson's statistic over the cells whose expected count is at least 5."""
    return sum((observed.get(cell, 0) - e) ** 2 / e for cell, e in expected.items() if e >= 5)


def castle_with(change: Callable[[dict[str, Any]], None]) -> Pack:
    """A copy of the castle pack after `change` edited its dumped form."""
    data = castle().model_dump(mode="json")
    change(data)
    return Pack.model_validate(data)
