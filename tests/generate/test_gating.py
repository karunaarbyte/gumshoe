import pytest

from gumshoe.cases.generate import gating as gating_stage
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, GatingOut, TruthOut
from tests.generate.helpers import PRESET_NAMES, castle, gating_of


def check_gating(truth: TruthOut, facts: FactsOut, gates: GatingOut) -> None:
    """The gating rules, written independently of the stage: one depth for every suspect, each
    suspect's chain made of their own facts only, every location open, and only the suspects
    nobody has to unlock open at the start. (The validator cannot see a missing gate where a
    shallower depth is also legal, so this check is the guard for the wiring.)"""
    suspects = [s.pos for s in truth.roster.suspects]
    kind = {s.pos: s.record_kind for s in truth.roster.suspects}
    assert gates.depth == facts.depth
    expected_records = {(kind[k], k, f"y_{k}") for k in suspects} if gates.depth >= 1 else set()
    found_records = {(g.kind, g.subject, g.fact) for g in gates.record_requires}
    assert found_records == expected_records
    expected_suspects = {(k, f"c_{k}") for k in suspects} if gates.depth == 2 else set()
    assert {(g.suspect, g.fact) for g in gates.suspect_requires} == expected_suspects
    assert len(gates.record_requires) == len(found_records)  # nothing gated twice
    assert gates.start_locations == tuple(loc.pos for loc in truth.roster.locations)
    locked = {g.suspect for g in gates.suspect_requires}
    assert set(gates.start_suspects) == set(suspects) - locked
    assert gates.start_facts == ()
    ids = {f.id for f in facts.facts}
    assert {g.fact for g in gates.record_requires} | {g.fact for g in gates.suspect_requires} <= ids


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_gating_follows_the_rules_at_every_feasible_depth(preset):
    pack = castle()
    for seed in range(60):
        ctx = GenContext.of(pack, seed, preset)
        _, _, drawn, _, _ = gating_of(ctx)
        located = sum(s.subject_type == "location" for s in drawn.record_sources)
        for depth in feasible_depths(ctx.spec, located):
            truth, _, facts, _, gates = gating_of(ctx, depth)
            check_gating(truth, facts, gates)


def test_the_stage_draws_nothing():
    """Gating only wires, so another stream gives the same output."""
    ctx = GenContext.of(castle(), 5, "long")
    truth, _, facts, placed, gates = gating_of(ctx)
    again = gating_stage.run(ctx, ctx.stream("gating", counter=3), truth, facts, placed)
    assert again == gates and again.digest() == gates.digest()


def test_every_depth_occurs_where_it_is_feasible():
    pack = castle()
    seen: dict[str, set[int]] = {}
    for preset in PRESET_NAMES:
        for seed in range(40):
            _, _, _, _, gates = gating_of(GenContext.of(pack, seed, preset))
            seen.setdefault(preset, set()).add(gates.depth)
    assert seen == {"short": {0, 1}, "standard": {0, 1, 2}, "long": {2}}


@pytest.mark.parametrize(("depth", "missing"), [(1, "y_"), (2, "c_")])
def test_a_missing_hint_or_key_raises_a_generation_error(depth, missing):
    preset = "standard"
    ctx = GenContext.of(castle(), 3, preset)
    truth, _, facts, placed, _ = gating_of(ctx, depth)
    without = facts.model_copy(
        update={"facts": tuple(f for f in facts.facts if not f.id.startswith(missing))}
    )
    with pytest.raises(GenerationError, match="which has no fact"):
        gating_stage.run(ctx, ctx.stream("gating"), truth, without, placed)
