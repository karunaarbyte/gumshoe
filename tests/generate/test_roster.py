import pytest

from gumshoe.cases.generate import roster as roster_stage
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import RosterOut
from gumshoe.cases.model.pack import Pack, TraceDef
from gumshoe.cases.packs.check.capacity import eligible_roles, hosting_scenes, usable_kind
from tests.generate.helpers import PRESET_NAMES, SEEDS, castle, roster_of


def draw(pack: Pack, seed: int, preset: str) -> tuple[GenContext, RosterOut]:
    ctx = GenContext.of(pack, seed, preset)
    return ctx, roster_of(ctx)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_roster_meets_the_sizes_and_the_pack_pools(preset):
    pack = castle()
    roles = {r.key: r for r in pack.roles}
    for seed in SEEDS:
        ctx, r = draw(pack, seed, preset)
        spec = ctx.spec
        scene = next(s for s in pack.scene_types if s.key == r.scene_type)
        assert scene in hosting_scenes(pack, spec)
        assert (len(r.suspects), len(r.methods), len(r.motives), len(r.locations)) == (
            spec.suspects,
            spec.methods,
            spec.motives,
            spec.locations,
        )
        assert len(r.record_kinds) == len(set(r.record_kinds)) == spec.record_kinds
        assert [s.pos for s in r.suspects] == [f"s{i}" for i in range(spec.suspects)]
        # distinct roles and names; every role eligible; label, aliases built from name and noun
        assert len({s.role for s in r.suspects}) == spec.suspects
        assert len({s.name for s in r.suspects}) == spec.suspects
        for s in r.suspects:
            assert s.role in eligible_roles(pack, scene)
            assert s.name in {e.text for e in roles[s.role].names}
            assert s.noun == roles[s.role].noun and s.label == f"{s.name} the {s.noun}"
            assert s.aliases == (s.name, f"the {s.noun}")
        # methods: distinct and allowed in the scene
        assert len({m.key for m in r.methods}) == spec.methods
        assert {m.key for m in r.methods} <= set(scene.allowed_methods)
        # motives: one per suspect, allowed for the role, distinct types (a perfect matching)
        assert len({m.key for m in r.motives}) == spec.motives
        by_pos = {m.pos: m for m in r.motives}
        assert len({s.motive_pos for s in r.suspects}) == spec.suspects
        for s in r.suspects:
            assert by_pos[s.motive_pos].key in roles[s.role].motive_types
        # locations: l0 is the scene, kinds distinct and known
        kinds = [loc.kind for loc in r.locations]
        assert kinds[0] == scene.location_kinds[0] and len(set(kinds)) == len(kinds)
        assert set(kinds) <= {d.key for d in pack.location_defs}
        assert not any(loc.decorative for loc in r.locations)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_contracts_a_b_c_and_g_prime_hold_for_every_seed(preset):
    pack = castle()
    records = {d.key: d for d in pack.record_defs}
    methods = {m.key: m for m in pack.method_defs}
    for seed in SEEDS:
        _, r = draw(pack, seed, preset)
        scene = next(s for s in pack.scene_types if s.key == r.scene_type)
        scene_kind = scene.location_kinds[0]
        others = {loc.kind for loc in r.locations[1:]}
        roles = {x.key: x for x in pack.roles}
        for s in r.suspects:
            # (a) the secret record kind is chosen, allowed for the role, and usable at the scene
            assert s.record_kind in r.record_kinds
            assert s.record_kind in roles[s.role].record_kinds
            assert usable_kind(records[s.record_kind], scene)
            # (b) and (b') it attests the scene kind and some other chosen place
            assert scene_kind in records[s.record_kind].location_kinds
            assert others & set(records[s.record_kind].location_kinds)
        for m in r.methods:  # (c) a trace of the method fits the scene and a non-scene place
            assert any(
                t.kind in scene.allowed_trace_kinds and others & set(t.location_kinds)
                for t in methods[m.key].traces
            )
        for kind in r.record_kinds:  # (g') a location-subject kind attests a chosen place
            if records[kind].subject == "location":
                assert ({scene_kind} | others) & set(records[kind].location_kinds)


def test_the_choices_vary_across_seeds():
    pack = castle()
    seen_scenes, seen_roles, seen_kinds = set(), set(), set()
    for seed in SEEDS:
        _, r = draw(pack, seed, "standard")
        seen_scenes.add(r.scene_type)
        seen_roles.add(frozenset(s.role for s in r.suspects))
        seen_kinds.add(r.record_kinds)
    assert len(seen_scenes) >= 4 and len(seen_roles) >= 20 and len(seen_kinds) >= 2


def test_the_stage_is_deterministic_and_reads_only_its_stream():
    pack = castle()
    _, a = draw(pack, 11, "long")
    _, b = draw(pack, 11, "long")
    assert a == b and a.digest() == b.digest()
    assert a.digest() != draw(pack, 12, "long")[1].digest()


def test_the_location_enumeration_is_never_empty_on_the_castle_for_any_reachable_draw():
    """Exhaustive: every hosting scene x record-kind set x set of kinds the suspects use x
    method subset has a feasible set of non-scene locations, so the stage never raises."""
    from itertools import combinations

    pack = castle()
    records = {d.key: d for d in pack.record_defs}
    methods = {m.key: m for m in pack.method_defs}
    for preset in PRESET_NAMES:
        ctx = GenContext.of(pack, 0, preset)
        spec = ctx.spec
        for scene in hosting_scenes(pack, spec):
            for kinds in combinations(sorted(pack.known_record_kinds), spec.record_kinds):
                usable = [k for k in kinds if usable_kind(records[k], scene)]
                for used_size in range(1, len(usable) + 1):
                    for used in combinations(usable, used_size):
                        for picked in combinations(sorted(scene.allowed_methods), spec.methods):
                            roster_stage.location_kinds(
                                pack,
                                scene,
                                list(used),
                                [methods[k] for k in picked],
                                kinds,
                                spec.locations,
                                ctx.stream("roster"),
                            )  # raises GenerationError when empty


def test_an_infeasible_pack_raises_a_generation_error_not_a_loop():
    pack = castle()
    nowhere = tuple(
        m.model_copy(
            update={
                "traces": tuple(
                    TraceDef(kind=t.kind, location_kinds=("nowhere",)) for t in m.traces
                )
            }
        )
        for m in pack.method_defs
    )
    broken = pack.model_copy(update={"method_defs": nowhere})
    ctx = GenContext.of(broken, 1, "short")  # still hosted: the hosting rule ignores traces
    with pytest.raises(GenerationError, match="locations"):
        roster_stage.run(ctx, ctx.stream("roster"))


def test_a_scene_with_two_location_kinds_is_refused():
    pack = castle()
    wide = tuple(
        s.model_copy(update={"location_kinds": ("chapel", "keep")}) for s in pack.scene_types
    )
    ctx = GenContext.of(pack.model_copy(update={"scene_types": wide}), 1, "short")
    with pytest.raises(GenerationError, match="exactly one location kind"):
        roster_stage.run(ctx, ctx.stream("roster"))


def shared_names(pack: Pack, count: int) -> Pack:
    """Every role draws from the same pool of names."""
    pool = pack.roles[0].names + pack.roles[1].names + pack.roles[2].names + pack.roles[3].names
    roles = tuple(r.model_copy(update={"names": pool[:count]}) for r in pack.roles)
    return pack.model_copy(update={"roles": roles})


def test_names_stay_distinct_when_roles_share_a_name_pool():
    pack = shared_names(castle(), 8)
    for seed in range(60):
        _, r = draw(pack, seed, "short")
        assert len({s.name for s in r.suspects}) == len(r.suspects)


def test_a_role_with_no_unused_name_raises_a_generation_error():
    ctx = GenContext.of(shared_names(castle(), 1), 1, "short")
    with pytest.raises(GenerationError, match="no unused name"):
        roster_stage.run(ctx, ctx.stream("roster"))


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_a_record_kind_with_no_definition_imposes_no_location_constraint(preset):
    pack = castle()
    bare = pack.model_copy(update={"record_kinds": (*pack.record_kinds, "aaa_bare")})
    defined = {d.key for d in pack.record_defs}
    for seed in range(40):
        _, r = draw(bare, seed, preset)
        assert all(s.record_kind in defined for s in r.suspects)
        assert set(r.record_kinds) <= defined


def test_no_record_kind_set_that_serves_every_role_raises_a_generation_error():
    """Every role is eligible, but each needs its own record kind and a set holds only K."""
    pack = castle()
    ledger = next(d for d in pack.record_defs if d.key == "visitor_ledger")
    keys = [f"ledger_{i}" for i in range(len(pack.roles))]
    defs = tuple(ledger.model_copy(update={"key": key}) for key in keys)
    roles = tuple(
        r.model_copy(update={"record_kinds": (key,)})
        for r, key in zip(pack.roles, keys, strict=True)
    )
    broken = pack.model_copy(
        update={"record_defs": defs, "roles": roles, "record_kinds": tuple(keys)}
    )
    ctx = GenContext.of(broken, 1, "short")
    with pytest.raises(GenerationError, match="record-kind set"):
        roster_stage.run(ctx, ctx.stream("roster"))


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_a_duplicate_in_allowed_methods_never_gives_a_duplicate_method(preset):
    pack = castle()
    doubled = tuple(
        s.model_copy(update={"allowed_methods": (*s.allowed_methods, s.allowed_methods[0])})
        for s in pack.scene_types
    )
    dup = pack.model_copy(update={"scene_types": doubled})
    for seed in range(60):
        _, r = draw(dup, seed, preset)
        assert len({m.key for m in r.methods}) == len(r.methods)
