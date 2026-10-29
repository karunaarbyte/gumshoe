"""Shared helpers for the generator tests."""

from collections.abc import Callable, Mapping
from math import sqrt
from typing import Any

import pytest

from gumshoe.cases.generate import facts, gating, placement, roster, timeline, truth
from gumshoe.cases.generate.assemble import build_case
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    FactsOut,
    GatingOut,
    PlacementOut,
    RosterOut,
    TimelineOut,
    TruthOut,
)
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.tools.registry import bundled_pack, bundled_packs
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.routes import best_solution

PRESET_NAMES = ("short", "standard", "long")
SEEDS = range(200)
GOLDEN_SEEDS = (0, 1, 2, 3, 4)
# One-sided p = 0.0005 per test, about 0.005 over the ten statistical tests of one pack. The
# statistical tests now run once per bundled pack, so the family-wise rate grows with the number
# of packs (about 0.005 x packs); the per-test level is kept so a real tell still fails.
Z_BONFERRONI = 3.29


def pack_of(pack_id: str) -> Pack:
    found = bundled_pack(pack_id)
    assert found is not None, pack_id
    return found


def castle() -> Pack:
    return pack_of("castle")


PACK_IDS = tuple(info.id for info in bundled_packs())
PACKS = [pytest.param(pack_id, id=pack_id) for pack_id in PACK_IDS]


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


def placement_of(
    ctx: GenContext, depth: int | None = None
) -> tuple[TruthOut, TimelineOut, FactsOut, PlacementOut]:
    """Everything up to and including placement; `depth` forces the gating depth."""
    after, tl, fa = facts_of(ctx, depth)
    return after, tl, fa, placement.run(ctx, ctx.stream("placement"), after, fa)


def gating_of(
    ctx: GenContext, depth: int | None = None
) -> tuple[TruthOut, TimelineOut, FactsOut, PlacementOut, GatingOut]:
    """Every stage output for a context; `depth` forces the gating depth."""
    after, tl, fa, placed = placement_of(ctx, depth)
    return after, tl, fa, placed, gating.run(ctx, ctx.stream("gating"), after, fa, placed)


def case_of(ctx: GenContext, depth: int | None = None) -> Case:
    """The skeleton-only case of a context, built from the stages called one by one."""
    return build_case(ctx, *gating_of(ctx, depth))


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


def solution_shape(case: Case) -> tuple[int, int, int]:
    """The cheapest solution's size, depth and actions, as the validator measures them."""
    ix = CaseIndex.of(case)
    best = best_solution(ix, build_graph(ix), compute_reach(ix).facts)
    assert best is not None
    return best.size, best.depth, best.actions
