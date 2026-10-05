import pytest

from gumshoe.cases.generate.assemble import build_case, generator_version
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import SKELETON_ALGO_VERSION, STAGES, GenContext
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Origin, SourceKind
from gumshoe.cases.model.serialize import dump_case, load_case, skin_dict
from tests.generate.helpers import PRESET_NAMES, castle, gating_of


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
    assert [part.split("=")[0] for part in generator_version().split(",")] == list(STAGES)
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
