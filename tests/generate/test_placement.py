from dataclasses import replace

import pytest

from gumshoe.cases.generate import placement as placement_stage
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, PlacementOut, TruthOut
from gumshoe.cases.model.pack import Pack
from tests.generate.helpers import PRESET_NAMES, SEEDS, castle, placement_of


def check_placement(
    pack: Pack, ctx: GenContext, truth: TruthOut, facts: FactsOut, placed: PlacementOut
) -> None:
    """The placement rules, written independently of the stage."""
    kind_of = {loc.pos: loc.kind for loc in truth.roster.locations}
    records = {d.key: d for d in pack.record_defs}
    search = {f.id: f for f in facts.facts if f.home.kind == "search"}
    where = {p.fact: p.location for p in placed.search}
    assert len(placed.search) == len(search) == len(where) and set(where) == set(search)
    assert set(where.values()) <= set(kind_of)
    load = {loc: list(where.values()).count(loc) for loc in kind_of}
    assert max(load.values()) <= ctx.spec.source_cap and min(load.values()) >= 1
    for fact in search.values():
        if fact.place_kinds:  # a decisive trace sits where its trace can be
            assert kind_of[where[fact.id]] in fact.place_kinds, fact.id
        if fact.apart_from:  # a clue never sits beside its trace
            assert where[fact.id] != where[fact.apart_from], fact.id
    assert ({f for f in search if f.startswith("c_")} != set()) == (facts.depth == 2)
    suspects = [r for r in placed.record_sources if r.subject_type == "suspect"]
    assert [(r.kind, r.subject) for r in suspects] == [
        (s.kind, s.subject) for s in facts.record_sources if s.subject
    ]
    wanted = [s.kind for s in facts.record_sources if s.subject is None]
    located = [r for r in placed.record_sources if r.subject_type == "location"]
    assert [r.kind for r in located] == wanted
    for r in located:
        assert kind_of[r.subject] in records[r.kind].location_kinds


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_placement_follows_the_rules_for_every_seed(preset):
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        truth, _, facts, placed = placement_of(ctx)
        check_placement(pack, ctx, truth, facts, placed)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_placement_follows_the_rules_at_every_feasible_depth(preset):
    pack = castle()
    for seed in range(60):
        ctx = GenContext.of(pack, seed, preset)
        truth, _, drawn, _ = placement_of(ctx)
        located = sum(s.subject_type == "location" for s in drawn.record_sources)
        for depth in feasible_depths(ctx.spec, located):
            truth, _, facts, placed = placement_of(ctx, depth)
            check_placement(pack, ctx, truth, facts, placed)


def test_the_load_is_spread_across_the_locations():
    """The least-loaded rule: no location holds more than two facts above the lightest."""
    pack = castle()
    for preset in PRESET_NAMES:
        for seed in SEEDS:
            ctx = GenContext.of(pack, seed, preset)
            truth, _, _, placed = placement_of(ctx)
            counts = [
                sum(p.location == loc.pos for p in placed.search) for loc in truth.roster.locations
            ]
            assert max(counts) - min(counts) <= 2, (preset, seed, counts)


def test_the_stage_is_deterministic_and_depends_on_the_seed():
    ctx = GenContext.of(castle(), 6, "standard")
    _, _, _, a = placement_of(ctx)
    _, _, _, b = placement_of(ctx)
    assert a == b and a.digest() == b.digest()
    assert a.digest() != placement_of(GenContext.of(castle(), 7, "standard"))[3].digest()


def test_a_decisive_trace_with_nowhere_to_go_raises_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    truth, _, facts, _ = placement_of(ctx)
    stuck = tuple(
        f.model_copy(update={"place_kinds": ("nowhere",)}) if f.id.startswith("h_") else f
        for f in facts.facts
    )
    with pytest.raises(GenerationError, match="no location with room"):
        placement_stage.run(
            ctx, ctx.stream("placement"), truth, facts.model_copy(update={"facts": stuck})
        )


def test_a_source_cap_too_small_for_the_facts_raises_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    truth, _, facts, _ = placement_of(ctx)
    tight = replace(ctx, spec=ctx.spec.model_copy(update={"source_cap": 1}))  # 6 facts, 3 places
    with pytest.raises(GenerationError, match="no location with room"):
        placement_stage.run(tight, tight.stream("placement"), truth, facts)


def test_a_location_left_without_a_fact_raises_a_generation_error():
    for seed in range(40):  # some seeds put two decisive traces together and leave one empty
        ctx = GenContext.of(castle(), seed, "short")
        truth, _, facts, _ = placement_of(ctx)
        bare = facts.model_copy(
            update={"facts": tuple(f for f in facts.facts if not f.id.startswith("p_"))}
        )
        try:
            placement_stage.run(ctx, ctx.stream("placement"), truth, bare)
        except GenerationError as error:
            assert "no search fact was placed" in str(error)
            return
    pytest.fail("no seed left a location empty")


def test_a_location_record_with_no_possible_subject_raises_a_generation_error():
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, "long")
        truth, _, facts, _ = placement_of(ctx)
        if not any(s.subject is None for s in facts.record_sources):
            continue
        defs = tuple(
            d.model_copy(update={"location_kinds": ("nowhere",)}) if d.subject == "location" else d
            for d in pack.record_defs
        )
        broken = replace(ctx, pack=pack.model_copy(update={"record_defs": defs}))
        with pytest.raises(GenerationError, match="can be the subject"):
            placement_stage.run(broken, broken.stream("placement"), truth, facts)
        return
    pytest.fail("no long seed has a location record")


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_location_holds_a_decisive_trace_in_most_cases(preset):
    """Ties between equally loaded locations are broken at random, not towards the first one."""
    pack = castle()
    counts: dict[str, int] = {}
    seeds = range(300)
    for seed in seeds:
        ctx = GenContext.of(pack, seed, preset)
        truth, _, facts, placed = placement_of(ctx)
        where = {p.fact: p.location for p in placed.search}
        holders = {where[f.id] for f in facts.facts if f.id.startswith("h_")}
        for loc in holders:
            counts[loc] = counts.get(loc, 0) + 1
        assert len(truth.roster.locations) == len({p.location for p in placed.search})
    assert min(counts.values()) >= 0.5 * len(seeds), counts  # castle: at least 0.7
