from dataclasses import replace
from math import sqrt

import pytest

from gumshoe.cases.core.ids import is_valid_id
from gumshoe.cases.generate import facts as facts_stage
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactDesc, FactsOut
from tests.generate.helpers import PRESET_NAMES, SEEDS, castle, facts_of, stages

DECISIVE = ("rules_out", "proves")


def by_suspect(out: FactsOut, k: str) -> dict[str, FactDesc]:
    """The facts a suspect owns, keyed by the id prefix (sec, e, x, w, y, l)."""
    return {f.id.split("_")[0]: f for f in out.facts if f.id.endswith(f"_{k}") and f.id[0] != "c"}


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_suspect_has_exactly_the_five_facts_of_their_category(preset):
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        truth, timeline, out = facts_of(ctx)
        for s in truth.roster.suspects:
            mine = by_suspect(out, s.pos)
            kinds = {name: f.kind for name, f in mine.items()}
            if s.pos == "s0" or s.pos in timeline.opportunity:
                assert kinds == {
                    "sec": "secret",
                    "e": "presence",
                    "x": "physical",
                    "y": "motive_clue",
                    "l": "lie",
                }, (preset, seed, s.pos)
            else:
                assert kinds == {
                    "sec": "secret",
                    "e": "alibi",
                    "w": "presence",
                    "y": "motive_clue",
                    "l": "lie",
                }, (preset, seed, s.pos)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_effects_polarity_follows_the_truth_and_the_opportunity(preset):
    pack = castle()
    for seed in SEEDS:
        truth, timeline, out = facts_of(GenContext.of(pack, seed, preset))
        for s in truth.roster.suspects:
            mine = by_suspect(out, s.pos)
            culprit, at_scene = s.pos == "s0", s.pos == "s0" or s.pos in timeline.opportunity
            assert [(e.axis, e.candidate, e.kind) for e in mine["sec"].effects] == [
                ("why", s.motive_pos, "proves" if culprit else "rules_out")
            ]
            assert [(e.axis, e.candidate, e.kind) for e in mine["e"].effects] == [
                ("who", s.pos, "supports" if at_scene else "rules_out")
            ]
            if at_scene:
                assert [(e.kind) for e in mine["x"].effects] == [
                    "proves" if culprit else "rules_out"
                ]
            else:
                assert [(e.kind) for e in mine["w"].effects] == ["supports"]
            assert [(e.axis, e.kind) for e in mine["y"].effects] == [("why", "supports")]
            assert [(e.axis, e.candidate, e.kind) for e in mine["l"].effects] == [
                ("who", s.pos, "rules_out")
            ]


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_claims_match_the_timeline_and_lies_contradict_it(preset):
    pack = castle()
    for seed in SEEDS:
        truth, timeline, out = facts_of(GenContext.of(pack, seed, preset))
        rows = {row.suspect_pos: row.places for row in timeline.rows}
        roster = truth.roster
        for s in roster.suspects:
            mine = by_suspect(out, s.pos)
            e, lie = mine["e"], mine["l"]
            assert e.claim is not None and lie.claim is not None
            assert (e.claim.slot, e.claim.place) == (
                timeline.crime_slot,
                rows[s.pos][timeline.crime_slot],
            )
            assert e.timeline_ref == (f"e_{s.pos}_{timeline.crime_slot}",)
            if "w" in mine:
                w = mine["w"].claim
                assert w is not None and w.slot != timeline.crime_slot
                assert w.place == rows[s.pos][w.slot]
            # the lie: a false place at the crime slot, never the scene, exposed by the own record
            assert lie.claim.slot == timeline.crime_slot
            assert lie.claim.place != rows[s.pos][timeline.crime_slot]
            assert lie.claim.place != roster.locations[0].pos
            assert lie.truthful is False and lie.speaker == s.pos
            assert lie.exposed_by == (e.id,)
            assert lie.exposure_hook == e.home
            assert e.home.target == s.record_kind and e.home.subject == s.pos


def test_the_second_presence_prefers_a_place_the_record_attests():
    pack = castle()
    records = {d.key: d for d in pack.record_defs}
    for preset in PRESET_NAMES:
        for seed in SEEDS:
            ctx = GenContext.of(pack, seed, preset)
            truth, timeline, out = facts_of(ctx)
            kind_of = {loc.pos: loc.kind for loc in truth.roster.locations}
            rows = {row.suspect_pos: row.places for row in timeline.rows}
            for s in truth.roster.suspects:
                w = by_suspect(out, s.pos).get("w")
                if w is None or w.claim is None:
                    continue
                attested = [
                    t
                    for t in range(ctx.spec.slots)
                    if t != timeline.crime_slot
                    and kind_of[rows[s.pos][t]] in records[s.record_kind].location_kinds
                ]
                if attested:
                    assert w.claim.slot in attested, (preset, seed, s.pos)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_method_facts_are_a_decisive_trace_that_needs_its_clue_found_elsewhere(preset):
    pack = castle()
    methods = {m.key: m for m in pack.method_defs}
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        truth, _, out = facts_of(ctx)
        roster = truth.roster
        scene = next(sc for sc in pack.scene_types if sc.key == roster.scene_type)
        chosen_kinds = {loc.kind for loc in roster.locations}
        facts = {f.id: f for f in out.facts}
        for m in roster.methods:
            h, p = facts[f"h_{m.pos}"], facts[f"p_{m.pos}"]
            assert h.kind == ("trace" if m.pos == "m0" else "absent_trace")
            assert [(e.axis, e.kind) for e in h.effects] == [
                ("how", "proves" if m.pos == "m0" else "rules_out")
            ]
            assert h.requires == (p.id,) and p.apart_from == h.id
            assert h.home.kind == p.home.kind == "search"
            trace = next(t for t in methods[m.key].traces if t.kind == h.trace_kind)
            assert h.trace_kind in scene.allowed_trace_kinds
            assert set(h.place_kinds) == set(trace.location_kinds)
            assert chosen_kinds & set(h.place_kinds)  # some chosen location can hold it
            assert [(e.axis, e.kind) for e in p.effects] == [("how", "supports")]


def shape(out: FactsOut, axis: str, candidate: str) -> tuple[tuple[str, str], ...]:
    """What the player can see of one candidate's truthful evidence: where and how decisive."""
    return tuple(
        sorted(
            (f.home.kind, "decisive" if e.kind in DECISIVE else "supports")
            for f in out.facts
            if f.truthful
            for e in f.effects
            if e.axis == axis and e.candidate == candidate
        )
    )


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_candidate_on_an_axis_has_the_same_evidence_shape(preset):
    pack = castle()
    for seed in SEEDS:
        truth, _, out = facts_of(GenContext.of(pack, seed, preset))
        roster = truth.roster
        for axis, positions in (
            ("who", [s.pos for s in roster.suspects]),
            ("how", [m.pos for m in roster.methods]),
            ("why", [m.pos for m in roster.motives]),
        ):
            assert len({shape(out, axis, c) for c in positions}) == 1, (preset, seed, axis)
        assert shape(out, "who", "s0") == (("record", "decisive"), ("record", "supports"))
        assert shape(out, "how", "m0") == (("search", "decisive"), ("search", "supports"))
        assert shape(out, "why", "v0") == (("interrogate", "supports"), ("record", "decisive"))


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_counts_ids_and_sources_follow_the_spec(preset):
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        truth, _, out = facts_of(ctx)
        spec, roster = ctx.spec, truth.roster
        subject = {d.key: d.subject for d in pack.record_defs}
        location_kinds = [k for k in roster.record_kinds if subject[k] == "location"]
        total = 5 * spec.suspects + 2 * spec.methods + len(location_kinds)
        total += spec.suspects if out.depth == 2 else 0
        assert len(out.facts) == total
        ids = [f.id for f in out.facts]
        assert len(set(ids)) == len(ids) and all(is_valid_id(i) for i in ids)
        assert len(out.record_sources) == spec.suspects + len(location_kinds)
        held = [(s.kind, s.subject) for s in out.record_sources if s.subject_type == "suspect"]
        assert held == [(s.record_kind, s.pos) for s in roster.suspects]
        located = [(s.kind, s.subject) for s in out.record_sources if s.subject_type == "location"]
        assert located == [(k, None) for k in location_kinds]
        for kind in location_kinds:
            neutral = next(f for f in out.facts if f.id == f"n_{kind}")
            assert (neutral.home.kind, neutral.home.target) == ("record", kind)
            assert not neutral.effects and neutral.claim is None
        keys = [f for f in out.facts if f.id.startswith("c_")]
        assert len(keys) == (spec.suspects if out.depth == 2 else 0)


def test_the_depth_is_drawn_from_the_feasible_set_and_can_be_forced():
    pack = castle()
    seen: dict[str, set[int]] = {p: set() for p in PRESET_NAMES}
    for preset in PRESET_NAMES:
        for seed in SEEDS:
            ctx = GenContext.of(pack, seed, preset)
            truth, _, out = facts_of(ctx)
            subject = {d.key: d.subject for d in pack.record_defs}
            records = sum(subject[k] == "location" for k in truth.roster.record_kinds)
            assert out.depth in feasible_depths(ctx.spec, records)
            seen[preset].add(out.depth)
    assert seen == {"short": {0, 1}, "standard": {0, 1, 2}, "long": {2}}  # every depth is drawn
    ctx = GenContext.of(pack, 1, "standard")
    for depth in (0, 1, 2):
        assert facts_of(ctx, depth)[2].depth == depth
    with pytest.raises(GenerationError, match="not feasible"):
        facts_of(GenContext.of(pack, 1, "short"), depth=2)  # search capacity: 10 against 9
    with pytest.raises(GenerationError, match="not feasible"):
        facts_of(GenContext.of(pack, 1, "long"), depth=0)  # misses the size and depth windows


def test_the_stage_is_deterministic_and_depends_on_the_seed():
    ctx = GenContext.of(castle(), 6, "standard")
    _, _, a = facts_of(ctx)
    _, _, b = facts_of(ctx)
    assert a == b and a.digest() == b.digest()
    assert a.digest() != facts_of(GenContext.of(castle(), 7, "standard"))[2].digest()


def test_a_method_with_no_trace_that_fits_the_scene_raises_a_generation_error():
    pack = castle()
    ctx = GenContext.of(pack, 2, "short")
    _, truth, timeline = stages(ctx)
    bare_methods = tuple(m.model_copy(update={"traces": ()}) for m in pack.method_defs)
    bare = pack.model_copy(update={"method_defs": bare_methods})
    bare_ctx = GenContext.of(bare, 2, "short")  # the same spec, so the same streams
    with pytest.raises(GenerationError, match="no trace that fits"):
        facts_stage.run(bare_ctx, bare_ctx.stream("facts"), truth, timeline)


def test_a_suspect_with_no_non_scene_place_to_lie_about_raises_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    roster, truth, timeline = stages(ctx)
    scene_only = truth.roster.model_copy(update={"locations": truth.roster.locations[:1]})
    squeezed = truth.model_copy(update={"roster": scene_only})
    with pytest.raises(GenerationError, match="no non-scene place"):
        facts_stage.run(ctx, ctx.stream("facts"), squeezed, timeline)


def test_a_preset_with_no_feasible_depth_raises_a_generation_error():
    ctx = GenContext.of(castle(), 2, "short")
    _, truth, timeline = stages(ctx)
    cramped = replace(ctx, spec=ctx.spec.model_copy(update={"source_cap": 2}))  # a record holds 3
    with pytest.raises(GenerationError, match="no gating depth fits"):
        facts_stage.run(cramped, cramped.stream("facts"), truth, timeline)


def _attested_lie_rates(preset, seeds):
    """Per class (culprit, opportunity, away): lies whose place kind the suspect's own record
    kind attests, as (hits, trials)."""
    pack = castle()
    records = {d.key: d for d in pack.record_defs}
    rates = {c: [0, 0] for c in ("culprit", "opportunity", "away")}
    for seed in seeds:
        ctx = GenContext.of(pack, seed, preset)
        truth, timeline, out = facts_of(ctx)
        kind_of = {loc.pos: loc.kind for loc in truth.roster.locations}
        lies = {f.id: f for f in out.facts if f.id.startswith("l_")}
        for s in truth.roster.suspects:
            where = "culprit" if s.pos == "s0" else "away"
            if s.pos in timeline.opportunity:
                where = "opportunity"
            place = lies[f"l_{s.pos}"].claim.place
            rates[where][0] += kind_of[place] in records[s.record_kind].location_kinds
            rates[where][1] += 1
    return rates


def test_a_lie_is_as_likely_to_name_an_attested_place_whoever_the_suspect_is():
    rates = _attested_lie_rates("standard", range(6000))
    away_hits, away_n = rates["away"]
    for who in ("culprit", "opportunity"):
        hits, n = rates[who]
        pooled = (hits + away_hits) / (n + away_n)
        se = sqrt(pooled * (1 - pooled) * (1 / n + 1 / away_n))
        z = (hits / n - away_hits / away_n) / se
        assert abs(z) < 3.3, (who, hits / n, away_hits / away_n, z)
