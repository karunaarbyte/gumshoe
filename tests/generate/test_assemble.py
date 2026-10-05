import re
from collections import Counter
from math import factorial, sqrt

import pytest

from gumshoe.cases.generate import assemble as assemble_module
from gumshoe.cases.generate.assemble import (
    PREFIXES,
    assemble,
    build_case,
    generator_version,
    id_map,
    rename,
)
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import PIPELINE, SKELETON_ALGO_VERSION, GenContext
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Origin, SourceKind
from gumshoe.cases.model.serialize import dump_case, load_case, skin_dict
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.generate.helpers import (
    PRESET_NAMES,
    castle,
    castle_with,
    chi2_critical,
    chi2_statistic,
    gating_of,
    solution_shape,
)


def check_case(ctx: GenContext, case: Case, outputs) -> None:
    """The assembled case says exactly what the stage outputs say (no validator involved)."""
    truth, timeline, facts, placed, gates = outputs
    roster = truth.roster
    assert (case.truth.who, case.truth.how, case.truth.why) == ("s0", "m0", "v0")
    assert [s.id for s in case.suspects] == sorted(s.pos for s in roster.suspects)
    assert {m.id: m.type for m in case.methods} == {m.pos: m.key for m in roster.methods}
    assert {v.id: v.type for v in case.motives} == {v.pos: v.key for v in roster.motives}
    assert {loc.id: loc.kind for loc in case.locations} == {
        loc.pos: loc.kind for loc in roster.locations
    }
    assert case.scene_type == roster.scene_type and case.spec == ctx.spec
    # the timeline: one event per suspect and slot, the crime in the culprit's crime-slot cell
    where = {(e.actor, e.slot): e.place for e in case.timeline}
    assert where == {
        (row.suspect_pos, slot): place
        for row in timeline.rows
        for slot, place in enumerate(row.places)
    }
    crimes = [e for e in case.timeline if e.action == "crime"]
    assert [(e.actor, e.slot, e.place) for e in crimes] == [("s0", timeline.crime_slot, "l0")]
    # the facts: every one, with its source from its home or from placement
    by_id = {f.id: f for f in case.facts}
    assert set(by_id) == {f.id for f in facts.facts}
    search = {p.fact: p.location for p in placed.search}
    located = {r.kind: r.subject for r in placed.record_sources if r.subject_type == "location"}
    for desc in facts.facts:
        fact = by_id[desc.id]
        assert fact.kind.value == desc.kind and fact.truthful == desc.truthful
        assert fact.speaker == desc.speaker and fact.trace_kind == desc.trace_kind
        assert fact.requires == tuple(sorted(desc.requires))
        assert fact.exposed_by == tuple(sorted(desc.exposed_by))
        assert fact.timeline_ref == tuple(sorted(desc.timeline_ref))
        assert sorted((e.axis.value, e.candidate, e.kind.value) for e in fact.effects) == sorted(
            (e.axis, e.candidate, e.kind) for e in desc.effects
        )
        if desc.claim is None:
            assert fact.claim is None
        else:
            assert fact.claim is not None
            assert (fact.claim.actor, fact.claim.slot, fact.claim.place) == (
                desc.claim.actor,
                desc.claim.slot,
                desc.claim.place,
            )
        home = desc.home
        expected = {
            "search": (SourceKind.SEARCH, search.get(desc.id), None),
            "interrogate": (SourceKind.INTERROGATE, home.target, None),
            "record": (SourceKind.RECORD, home.target, home.subject or located.get(home.target)),
        }[home.kind]
        assert (fact.source.kind, fact.source.target, fact.source.subject) == expected
        if desc.exposure_hook is not None:
            assert fact.exposure_hook == by_id[desc.exposed_by[0]].source
    # the suspects: their secret, what they can speak, and their gate
    gated = {g.suspect: g.fact for g in gates.suspect_requires}
    for s in case.suspects:
        assert s.secret_fact == f"sec_{s.id}"
        assert s.knows == (f"l_{s.id}", f"y_{s.id}")
        assert s.requires == ((gated[s.id],) if s.id in gated else ())
    # record sources with their gates, and the start
    record_gates = {(g.kind, g.subject): g.fact for g in gates.record_requires}
    assert sorted((r.kind, r.subject_type.value, r.subject) for r in case.record_sources) == sorted(
        (r.kind, r.subject_type, r.subject) for r in placed.record_sources
    )
    for r in case.record_sources:
        gate = record_gates.get((r.kind, r.subject))
        assert r.requires == ((gate,) if gate else ())
    assert case.start.locations == tuple(sorted(gates.start_locations))
    assert case.start.suspects == tuple(sorted(gates.start_suspects))
    assert case.start.facts == ()


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_case_says_what_the_stage_outputs_say(preset):
    pack = castle()
    for seed in range(40):
        ctx = GenContext.of(pack, seed, preset)
        outputs = gating_of(ctx)
        check_case(ctx, build_case(ctx, *outputs), outputs)


def test_the_case_carries_its_meta_and_no_skin():
    pack = castle()
    ctx = GenContext.of(pack, 6, "standard")
    case = build_case(ctx, *gating_of(ctx))
    assert case.origin is Origin.GENERATED and case.seed == 6
    assert case.pack_ref is not None
    assert (case.pack_ref.id, case.pack_ref.skeleton_hash) == (pack.id, pack.skeleton_hash())
    assert case.skeleton_algo_version == SKELETON_ALGO_VERSION
    assert case.generator_version == generator_version()
    assert [part.split("=")[0] for part in generator_version().split(",")] == list(PIPELINE)
    blank = skin_dict(build_case(ctx, *gating_of(ctx)))
    assert all(not value for value in _leaves(blank)), "a skin field is filled"
    assert load_case(dump_case(case)) == case  # it round-trips through the canonical form


def _leaves(value):
    """Every skin value, skipping the entity ids `skin_dict` keys them by."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key != "id":
                yield from _leaves(item)
    elif isinstance(value, list) and value and isinstance(value[0], (dict, list)):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


def test_the_case_id_depends_on_the_seed_and_the_preset():
    pack = castle()
    ids = set()
    for preset in PRESET_NAMES:
        for seed in range(3):
            ctx = GenContext.of(pack, seed, preset)
            ids.add(build_case(ctx, *gating_of(ctx)).id)
    assert len(ids) == 9


def test_a_search_fact_that_was_not_placed_raises_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    truth, timeline, facts, placed, gates = gating_of(ctx)
    dropped = placed.model_copy(update={"search": placed.search[1:]})
    with pytest.raises(GenerationError, match="did not place"):
        build_case(ctx, truth, timeline, facts, dropped, gates)


def test_a_location_record_without_a_subject_raises_a_generation_error():
    pack = castle()
    for seed in range(60):
        ctx = GenContext.of(pack, seed, "long")
        truth, timeline, facts, placed, gates = gating_of(ctx)
        if not any(r.subject_type == "location" for r in placed.record_sources):
            continue
        suspects_only = tuple(r for r in placed.record_sources if r.subject_type == "suspect")
        bare = placed.model_copy(update={"record_sources": suspects_only})
        with pytest.raises(GenerationError, match="no subject"):
            build_case(ctx, truth, timeline, facts, bare, gates)
        return
    pytest.fail("no long seed has a location record")


# Final ids


def final_case(ctx: GenContext, depth: int | None = None):
    outputs = gating_of(ctx, depth)
    return build_case(ctx, *outputs), assemble(ctx, *outputs)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_final_ids_keep_no_neutral_position_and_say_nothing_about_a_fact(preset):
    pack = castle()
    pattern = re.compile(r"[smvlef]_[0-9a-f]{8}")
    for seed in range(30):
        ctx = GenContext.of(pack, seed, preset)
        skeleton, final = final_case(ctx)
        text = dump_case(final).decode()
        neutral = {e.id for e in (*skeleton.suspects, *skeleton.methods, *skeleton.motives)}
        neutral |= {e.id for e in (*skeleton.locations, *skeleton.timeline, *skeleton.facts)}
        assert not [i for i in neutral if f'"{i}"' in text], (preset, seed)
        entities = [*final.suspects, *final.methods, *final.motives, *final.locations]
        entities += [*final.timeline, *final.facts]
        assert all(pattern.fullmatch(e.id) for e in entities)
        assert len({e.id for e in entities}) == len(entities) == len(neutral)
        assert {f.id[0] for f in final.facts} == {PREFIXES["fact"]}  # one prefix for every kind


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_renaming_every_id_back_gives_the_neutral_case(preset):
    pack = castle()
    for seed in range(30):
        ctx = GenContext.of(pack, seed, preset)
        skeleton, final = final_case(ctx)
        names = id_map(skeleton)
        assert rename(final, {new: old for old, new in names.items()}) == skeleton


def test_a_colliding_id_raises_the_salt_until_it_is_free(monkeypatch):
    ctx = GenContext.of(castle(), 2, "short")
    skeleton = build_case(ctx, *gating_of(ctx))

    def collide(prefix, *parts):  # entities 2k and 2k + 1 of a kind get the same hash
        _, _, index, salt = parts
        return f"{prefix}_{index // 2:04x}{salt:04x}"

    monkeypatch.setattr(assemble_module, "make_id", collide)
    names = id_map(skeleton)
    assert len(set(names.values())) == len(names)
    assert any(new.endswith("0001") for new in names.values())  # a salt of 1 was needed
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{1,31}", new) for new in names.values())


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_a_renamed_case_has_the_verdict_of_the_neutral_case_at_every_feasible_depth(preset):
    pack = castle()
    for seed in range(40):
        ctx = GenContext.of(pack, seed, preset)
        _, _, drawn, *_ = gating_of(ctx)
        located = sum(r.subject_type == "location" for r in drawn.record_sources)
        for depth in feasible_depths(ctx.spec, located):
            skeleton, final = final_case(ctx, depth)
            assert validate(final, pack, Profile.STRICT).issues == (), (preset, seed, depth)
            assert solution_shape(final) == solution_shape(skeleton), (preset, seed, depth)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_no_ordering_of_the_ids_points_at_the_truth(preset):
    """The cases list their entities by id, so the id hash is the only order a player sees: the
    truth must sit at every rank equally often, and a suspect's motive must not follow their own
    rank (the truth stage makes suspect k's motive v_k, which the ids must not carry over)."""
    pack, seeds = castle(), range(500)
    ranks: dict[str, Counter[int]] = {axis: Counter() for axis in ("who", "how", "why")}
    order_preserving = 0
    for seed in seeds:
        ctx = GenContext.of(pack, seed, preset)
        case = assemble(ctx, *gating_of(ctx))
        for axis, entities, truth in (
            ("who", case.suspects, case.truth.who),
            ("how", case.methods, case.truth.how),
            ("why", case.motives, case.truth.why),
        ):
            ranks[axis][[e.id for e in entities].index(truth)] += 1
        motives = [s.motive for s in case.suspects]  # the suspects in id order
        order_preserving += motives == sorted(motives)
    for axis, found in ranks.items():
        size = {"who": ctx.spec.suspects, "how": ctx.spec.methods, "why": ctx.spec.motives}[axis]
        expected = {rank: len(seeds) / size for rank in range(size)}
        assert chi2_statistic(found, expected) <= chi2_critical(size - 1), (axis, found)
    chance = 1 / factorial(ctx.spec.suspects)
    sigma = sqrt(chance * (1 - chance) / len(seeds))
    assert order_preserving / len(seeds) <= chance + 3 * sigma, order_preserving


def test_the_same_seed_has_other_ids_in_another_preset_and_in_another_pack():
    """The code of a case is (seed, preset, pack): a player who knows the ids of one must not see
    them again in another (the truth's ids are index 0 of their kind in every case)."""
    pack = castle()
    renamed = castle_with(lambda data: data.__setitem__("id", "castle_two"))
    for seed in range(20):
        truths = []
        for preset in PRESET_NAMES:
            ctx = GenContext.of(pack, seed, preset)
            truths.append(assemble(ctx, *gating_of(ctx)).truth)
        other = GenContext.of(renamed, seed, "short")
        truths.append(assemble(other, *gating_of(other)).truth)
        for axis in ("who", "how", "why"):
            ids = [getattr(t, axis) for t in truths]
            assert len(set(ids)) == len(ids), (seed, axis)


def test_a_location_gate_is_renamed_with_the_rest():
    """Gating never gates a location today, but the field is part of the case: rename it."""
    ctx = GenContext.of(castle(), 2, "short")
    skeleton = build_case(ctx, *gating_of(ctx))
    fact, gated = skeleton.facts[0].id, skeleton.locations[1]
    case = skeleton.model_copy(
        update={
            "locations": tuple(
                loc.model_copy(update={"requires": (fact,)}) if loc.id == gated.id else loc
                for loc in skeleton.locations
            )
        }
    )
    names = id_map(skeleton)
    renamed = next(loc for loc in rename(case, names).locations if loc.id == names[gated.id])
    assert renamed.requires == (names[fact],)


def test_a_stage_output_that_makes_no_case_is_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    truth, timeline, facts, placed, gates = gating_of(ctx)
    dangling = gates.model_copy(update={"start_facts": ("nope",)})
    with pytest.raises(GenerationError, match="does not make a case"):
        assemble(ctx, truth, timeline, facts, placed, dangling)
