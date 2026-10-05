import pytest

from gumshoe.cases.generate import timeline as timeline_stage
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, PlacementOut, RosterOut, TimelineOut, TruthOut
from gumshoe.cases.tools.builtin import load_builtin_pack
from gumshoe.cases.tools.gen_dev import replay


def castle():
    return load_builtin_pack("castle")


def test_replay_returns_every_stage_up_to_the_requested_one():
    pack = castle()
    assert list(replay(3, "short", pack, "roster")) == ["roster"]
    assert list(replay(3, "short", pack, "truth")) == ["roster", "truth"]
    assert list(replay(3, "short", pack, "timeline")) == ["roster", "truth", "timeline"]
    full = replay(3, "short", pack)  # the default is every stage
    assert list(full) == ["roster", "truth", "timeline", "facts", "placement"]
    assert isinstance(full["roster"], RosterOut) and isinstance(full["timeline"], TimelineOut)
    assert isinstance(full["facts"], FactsOut) and isinstance(full["placement"], PlacementOut)


def test_replay_is_deterministic_and_a_prefix_of_the_full_run():
    pack = castle()
    assert replay(3, "standard", pack) == replay(3, "standard", pack)
    partial = replay(3, "standard", pack, "truth")
    assert partial["truth"].digest() == replay(3, "standard", pack)["truth"].digest()


def test_an_override_replaces_one_stage_and_reruns_only_the_later_ones():
    pack = castle()
    base = replay(3, "short", pack)
    other = replay(4, "short", pack, "roster")["roster"]
    changed = replay(3, "short", pack, override={"roster": other})
    assert changed["roster"] == other
    new_truth = changed["truth"]
    assert isinstance(new_truth, TruthOut)
    assert new_truth.roster.scene_type == other.scene_type  # type: ignore[attr-defined]
    assert new_truth != base["truth"]
    ctx = GenContext.of(pack, 3, "short")
    # the later stage ran on the truth built from the overridden roster
    assert changed["timeline"] == timeline_stage.run(ctx, ctx.stream("timeline"), new_truth)
    keep_truth = replay(3, "short", pack, override={"truth": base["truth"]})
    # overriding a stage with its own output changes nothing but the roster entry, which becomes
    # the truth's (reordered) roster
    assert keep_truth["truth"] == base["truth"] and keep_truth["timeline"] == base["timeline"]
    assert keep_truth["roster"] == base["truth"].roster  # type: ignore[attr-defined]


def test_a_truth_override_replaces_the_roster_entry_by_its_roster():
    pack = castle()
    other = replay(4, "short", pack, "truth")["truth"]
    changed = replay(3, "short", pack, override={"truth": other})
    assert isinstance(other, TruthOut)
    assert changed["roster"] == other.roster
    both = replay(
        3,
        "short",
        pack,
        override={"truth": other, "roster": replay(4, "short", pack, "roster")["roster"]},
    )
    assert both["roster"] == replay(4, "short", pack, "roster")["roster"]


def test_replay_rejects_unknown_stages_and_wrongly_typed_overrides():
    pack = castle()
    with pytest.raises(ValueError, match="unknown stage"):
        replay(3, "short", pack, "gating")
    with pytest.raises(ValueError, match="unknown override"):
        replay(3, "short", pack, override={"gating": replay(3, "short", pack, "roster")["roster"]})
    roster = replay(3, "short", pack, "roster")["roster"]
    with pytest.raises(TypeError, match="truth override must be a TruthOut"):
        replay(3, "short", pack, override={"truth": roster})
    with pytest.raises(TypeError, match="timeline override must be a TimelineOut"):
        replay(3, "short", pack, override={"timeline": roster})


def test_the_fold_gives_what_calling_the_stages_one_by_one_gives():
    from tests.generate.helpers import placement_of, stages

    pack = castle()
    for preset in ("short", "standard", "long"):
        ctx = GenContext.of(pack, 8, preset)
        roster, truth, timeline = stages(ctx)
        _, _, facts, placed = placement_of(ctx)
        full = replay(8, preset, pack)
        expected = (roster, truth, timeline, facts, placed)
        assert tuple(full[s] for s in ("roster", "truth", "timeline", "facts", "placement")) == (
            expected
        )


def test_overrides_that_do_not_fit_the_spec_or_each_other_are_refused():
    pack = castle()
    long_roster = replay(3, "long", pack, "roster")["roster"]
    with pytest.raises(ValueError, match="roster override"):
        replay(3, "short", pack, override={"roster": long_roster})
    short_truth = replay(3, "short", pack, "truth")["truth"]
    with pytest.raises(ValueError, match="truth override"):
        replay(3, "long", pack, override={"truth": short_truth})
    other_roster = replay(4, "short", pack, "roster")["roster"]
    with pytest.raises(ValueError, match="same people"):
        replay(3, "short", pack, override={"truth": short_truth, "roster": other_roster})
    timeline = replay(3, "short", pack)["timeline"]
    rows = timeline.rows  # type: ignore[attr-defined]
    fewer = timeline.model_copy(update={"rows": rows[:-1]})
    with pytest.raises(ValueError, match="timeline override"):
        replay(3, "short", pack, override={"timeline": fewer})
    thin = timeline.model_copy(update={"opportunity": ()})
    with pytest.raises(ValueError, match="timeline override"):
        replay(3, "short", pack, override={"timeline": thin})


def test_a_facts_override_replaces_the_facts_and_must_fit_the_truth_and_the_preset():
    pack = castle()
    base = replay(3, "standard", pack)
    assert replay(3, "standard", pack, override={"facts": base["facts"]}) == base
    short_facts = replay(3, "short", pack)["facts"]
    with pytest.raises(ValueError, match="facts override must have a record"):
        replay(3, "standard", pack, override={"facts": short_facts})  # 4 suspects, not 5
    assert isinstance(base["facts"], FactsOut)
    deep = base["facts"].model_copy(update={"depth": 7})
    with pytest.raises(ValueError, match="depth 7"):
        replay(3, "standard", pack, override={"facts": deep})
    wrong_kind = tuple(
        src.model_copy(update={"kind": "nowhere"}) if src.subject == "s0" else src
        for src in base["facts"].record_sources
    )
    with pytest.raises(ValueError, match="record for each"):
        replay(
            3,
            "standard",
            pack,
            override={"facts": base["facts"].model_copy(update={"record_sources": wrong_kind})},
        )
    no_trace = tuple(f for f in base["facts"].facts if f.id != "h_m0")
    with pytest.raises(ValueError, match="trace for each"):
        replay(
            3,
            "standard",
            pack,
            override={"facts": base["facts"].model_copy(update={"facts": no_trace})},
        )


def test_a_facts_override_must_have_the_truths_location_records():
    pack = castle()
    base = replay(0, "short", pack)  # one location record, depth 1
    assert isinstance(base["facts"], FactsOut)
    facts = base["facts"]
    located = [s for s in facts.record_sources if s.subject_type == "location"]
    assert len(located) == 1
    for sources in (
        tuple(s for s in facts.record_sources if s not in located),
        facts.record_sources + (located[0].model_copy(update={"kind": "nowhere"}),),
    ):
        with pytest.raises(ValueError, match="record source for each of the truth's location"):
            replay(
                0,
                "short",
                pack,
                override={"facts": facts.model_copy(update={"record_sources": sources})},
            )


def test_a_facts_override_has_keys_only_at_depth_2():
    pack = castle()
    shallow = replay(0, "short", pack)["facts"]  # depth 1
    deep = replay(0, "long", pack)["facts"]  # depth 2
    assert isinstance(shallow, FactsOut) and isinstance(deep, FactsOut)
    assert shallow.depth == 1 and deep.depth == 2
    extra = shallow.facts[0].model_copy(update={"id": "c_s0"})
    with pytest.raises(ValueError, match="keys only at depth 2"):
        replay(
            0,
            "short",
            pack,
            override={"facts": shallow.model_copy(update={"facts": shallow.facts + (extra,)})},
        )
    no_keys = tuple(f for f in deep.facts if not f.id.startswith("c_"))
    with pytest.raises(ValueError, match="keys only at depth 2"):
        replay(0, "long", pack, override={"facts": deep.model_copy(update={"facts": no_keys})})


def test_a_timeline_override_must_fit_the_slots_the_suspects_and_the_places():
    pack = castle()
    base = replay(3, "standard", pack)
    timeline = base["timeline"]
    assert isinstance(timeline, TimelineOut)
    for slot in (0, 3):  # the crime slot is neither the first nor the last of the four slots
        with pytest.raises(ValueError, match="crime slot"):
            replay(
                3,
                "standard",
                pack,
                override={"timeline": timeline.model_copy(update={"crime_slot": slot})},
            )
    first = timeline.rows[0]
    stray = first.model_copy(update={"places": ("l99", *first.places[1:])})
    other = first.model_copy(update={"suspect_pos": "s9"})
    for rows, match in (
        ((stray, *timeline.rows[1:]), "places outside the roster"),
        ((other, *timeline.rows[1:]), "row for each"),
    ):
        with pytest.raises(ValueError, match=match):
            replay(
                3,
                "standard",
                pack,
                override={"timeline": timeline.model_copy(update={"rows": rows})},
            )
    for opportunity in (("s0", *timeline.opportunity[1:]), ("s9", *timeline.opportunity[1:])):
        with pytest.raises(ValueError, match="opportunity must be wrong suspects"):
            replay(
                3,
                "standard",
                pack,
                override={"timeline": timeline.model_copy(update={"opportunity": opportunity})},
            )


def test_a_roster_override_must_use_defined_record_kinds_each_suspect_holds_one_and_nobody_two():
    pack = castle()
    base = replay(3, "standard", pack, "roster")["roster"]
    assert isinstance(base, RosterOut)
    subject = {d.key: d.subject for d in pack.record_defs}
    allowed = {r.key: set(r.record_kinds) for r in pack.roles}

    def fails(roster, match):
        with pytest.raises(ValueError, match=match):
            replay(3, "standard", pack, override={"roster": roster})

    fails(
        base.model_copy(update={"record_kinds": ("nowhere", *base.record_kinds[1:])}), "undefined"
    )
    # a suspect given a kind of the roster that their role does not allow
    for s in base.suspects:
        wrong = next((k for k in base.record_kinds if k not in allowed[s.role]), None)
        if wrong:
            swapped = tuple(
                t.model_copy(update={"record_kind": wrong}) if t.pos == s.pos else t
                for t in base.suspects
            )
            fails(base.model_copy(update={"suspects": swapped}), "does not allow")
            break
    else:
        raise AssertionError("no suspect with a kind their role does not allow")
    # a suspect who alone held a kind takes another, so nobody holds the first
    for seed in range(40):
        roster = replay(seed, "standard", pack, "roster")["roster"]
        assert isinstance(roster, RosterOut)
        held = [t.record_kind for t in roster.suspects]
        for t in roster.suspects:
            other = next(
                (k for k in roster.record_kinds if k != t.record_kind and k in allowed[t.role]),
                None,
            )
            if held.count(t.record_kind) == 1 and subject[t.record_kind] == "suspect" and other:
                moved = tuple(
                    u.model_copy(update={"record_kind": other}) if u.pos == t.pos else u
                    for u in roster.suspects
                )
                with pytest.raises(ValueError, match="nobody holds"):
                    replay(
                        seed,
                        "standard",
                        pack,
                        override={"roster": roster.model_copy(update={"suspects": moved})},
                    )
                break
        else:
            continue
        break
    else:
        raise AssertionError("no roster with a kind held by one suspect who could take another")
    # a kind the roster does not list
    out_of_set = next(k for k in subject if k not in base.record_kinds)
    for t in base.suspects:
        if out_of_set in allowed[t.role]:
            moved = tuple(
                u.model_copy(update={"record_kind": out_of_set}) if u.pos == t.pos else u
                for u in base.suspects
            )
            fails(base.model_copy(update={"suspects": moved}), "not a suspect record kind")
            break
    else:
        raise AssertionError("no suspect can take a kind outside the roster")


def _facts_fail(facts, match):
    with pytest.raises(ValueError, match=match):
        replay(3, "standard", castle(), override={"facts": facts})


def _edit_fact(facts, fact_id, **changes):
    edited = tuple(f.model_copy(update=changes) if f.id == fact_id else f for f in facts.facts)
    return facts.model_copy(update={"facts": edited})


def test_a_facts_override_has_unique_ids_the_truths_sources_once_and_references_that_resolve():
    facts = replay(3, "standard", castle())["facts"]
    assert isinstance(facts, FactsOut)
    _facts_fail(facts.model_copy(update={"facts": (*facts.facts, facts.facts[0])}), "id more than")
    twice = facts.model_copy(
        update={"record_sources": (*facts.record_sources, facts.record_sources[0])}
    )
    _facts_fail(twice, "record source of the truth exactly once")
    _facts_fail(_edit_fact(facts, "l_s0", exposed_by=("e_zz",)), "exposed_by 'e_zz'")
    _facts_fail(_edit_fact(facts, "h_m0", requires=("p_zz",)), "requires 'p_zz'")
    _facts_fail(_edit_fact(facts, "p_m0", apart_from="h_zz"), "apart_from 'h_zz'")


def test_a_facts_override_has_effects_on_the_truths_candidates_and_claims_inside_the_case():
    facts = replay(3, "standard", castle())["facts"]
    assert isinstance(facts, FactsOut)
    effect = facts.facts[1].effects[0]
    for candidate, axis in (("s9", effect.axis), (effect.candidate, "how")):
        bad = effect.model_copy(update={"candidate": candidate, "axis": axis})
        _facts_fail(_edit_fact(facts, facts.facts[1].id, effects=(bad,)), "effect on")
    claim = next(f.claim for f in facts.facts if f.id == "e_s0")
    assert claim is not None
    for change in ({"slot": 99}, {"slot": -1}, {"place": "l99"}):
        _facts_fail(_edit_fact(facts, "e_s0", claim=claim.model_copy(update=change)), "outside")


def test_a_placement_override_replaces_the_placement_and_must_fit_the_facts():
    pack = castle()
    base = replay(3, "standard", pack)
    assert replay(3, "standard", pack, override={"placement": base["placement"]}) == base
    placed = base["placement"]
    assert isinstance(placed, PlacementOut)
    first = placed.search[0]

    def fails(update, match):
        edited = placed.model_copy(update=update)
        with pytest.raises(ValueError, match=match):
            replay(3, "standard", pack, override={"placement": edited})

    fails({"search": placed.search[1:]}, "each search fact exactly once")
    fails({"search": (*placed.search, first)}, "each search fact exactly once")
    moved = placed.search[1:] + (first.model_copy(update={"location": "l9"}),)
    fails({"search": moved}, "location the roster lacks")
    crowded = tuple(p.model_copy(update={"location": "l0"}) for p in placed.search)
    fails(
        {"search": crowded}, "beside|cannot be|overfills"
    )  # a rule breaks, whichever is seen first
    fails({"record_sources": placed.record_sources[1:]}, "keep the suspects' record sources")
    wrong_subject = tuple(
        r.model_copy(update={"subject": "s0"}) if r.subject_type == "suspect" else r
        for r in placed.record_sources
    )
    fails({"record_sources": wrong_subject}, "keep the suspects' record sources")


def test_a_placement_override_must_respect_the_trace_places_and_the_clue_rule():
    pack = castle()
    base = replay(3, "standard", pack)
    placed, facts = base["placement"], base["facts"]
    assert isinstance(placed, PlacementOut) and isinstance(facts, FactsOut)
    by_id = {f.id: f for f in facts.facts}
    where = {p.fact: p.location for p in placed.search}
    clue = next(f for f in facts.facts if f.id.startswith("p_"))
    trace = by_id[clue.apart_from or ""]
    beside = tuple(
        p.model_copy(update={"location": where[trace.id]}) if p.fact == clue.id else p
        for p in placed.search
    )
    with pytest.raises(ValueError, match="beside"):
        replay(
            3,
            "standard",
            pack,
            override={"placement": placed.model_copy(update={"search": beside})},
        )
    kind_of = {loc.pos: loc.kind for loc in base["roster"].locations}  # type: ignore[attr-defined]
    for decisive in (f for f in facts.facts if f.id.startswith("h_")):
        bad = [loc for loc, kind in kind_of.items() if kind not in decisive.place_kinds]
        if bad:
            break
    else:
        pytest.fail("every trace fits every location here")
    elsewhere = tuple(
        p.model_copy(update={"location": bad[0]}) if p.fact == decisive.id else p
        for p in placed.search
    )
    edited = placed.model_copy(update={"search": elsewhere})
    with pytest.raises(ValueError, match="cannot be"):
        replay(3, "standard", pack, override={"placement": edited})


def test_a_placement_override_must_not_overfill_or_empty_a_location():
    pack = castle()
    for seed in range(60):
        base = replay(seed, "standard", pack)
        placed, facts = base["placement"], base["facts"]
        assert isinstance(placed, PlacementOut) and isinstance(facts, FactsOut)
        where = {p.fact: p.location for p in placed.search}
        load = {loc: list(where.values()).count(loc) for loc in set(where.values())}
        apart = {f.id: f.apart_from for f in facts.facts if f.apart_from}
        for clue, trace in apart.items():
            if load[where[clue]] != 1:
                continue
            target = next(loc for loc in load if loc not in (where[clue], where[trace or ""]))
            moved = tuple(
                p.model_copy(update={"location": target}) if p.fact == clue else p
                for p in placed.search
            )
            edited = placed.model_copy(update={"search": moved})
            with pytest.raises(ValueError, match="leaves a location empty"):
                replay(seed, "standard", pack, override={"placement": edited})
            return
    pytest.fail("no standard seed has a clue alone at its location")


def test_a_placement_override_must_give_each_location_record_a_fitting_subject():
    pack = castle()
    for seed in range(200):
        base = replay(seed, "long", pack)
        placed, roster = base["placement"], base["roster"]
        assert isinstance(placed, PlacementOut)
        located = [r for r in placed.record_sources if r.subject_type == "location"]
        if not located:
            continue
        records = {d.key: d for d in pack.record_defs}
        kind_of = {loc.pos: loc.kind for loc in roster.locations}  # type: ignore[attr-defined]
        record = located[0]
        bad = [
            loc for loc, kind in kind_of.items() if kind not in records[record.kind].location_kinds
        ]
        if not bad:
            continue
        wrong = tuple(
            r.model_copy(update={"subject": bad[0]}) if r == record else r
            for r in placed.record_sources
        )
        with pytest.raises(ValueError, match="bad location"):
            replay(
                seed,
                "long",
                pack,
                override={"placement": placed.model_copy(update={"record_sources": wrong})},
            )
        missing = tuple(r for r in placed.record_sources if r != record)
        with pytest.raises(ValueError, match="source for each location record"):
            replay(
                seed,
                "long",
                pack,
                override={"placement": placed.model_copy(update={"record_sources": missing})},
            )
        return
    pytest.fail("no long seed has a location record with a disallowed location")


def test_a_placement_override_must_not_overfill_a_location():
    pack = castle()
    base = replay(3, "long", pack)
    placed, facts = base["placement"], base["facts"]
    assert isinstance(placed, PlacementOut) and isinstance(facts, FactsOut)
    where = {p.fact: p.location for p in placed.search}
    keys = sorted(f.id for f in facts.facts if f.id.startswith("c_"))  # a key may sit anywhere
    target = where[keys[0]]
    for key in keys[1:]:
        values = list(where.values())
        if values.count(target) <= 4 and values.count(where[key]) >= 2:
            where[key] = target
    assert list(where.values()).count(target) > 4
    moved = tuple(p.model_copy(update={"location": where[p.fact]}) for p in placed.search)
    edited = placed.model_copy(update={"search": moved})
    with pytest.raises(ValueError, match="overfills"):
        replay(3, "long", pack, override={"placement": edited})


def test_a_placement_override_must_not_add_or_change_the_kind_of_a_record_source():
    pack = castle()
    base = replay(3, "long", pack)
    placed = base["placement"]
    assert isinstance(placed, PlacementOut)
    extra = placed.record_sources[0].model_copy(update={"subject_type": "event"})
    edited = placed.model_copy(update={"record_sources": (*placed.record_sources, extra)})
    with pytest.raises(ValueError, match="about neither a suspect nor a location"):
        replay(3, "long", pack, override={"placement": edited})
