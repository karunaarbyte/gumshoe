import pytest

from gumshoe.cases.generate import timeline as timeline_stage
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, RosterOut, TimelineOut, TruthOut
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
    assert list(full) == ["roster", "truth", "timeline", "facts"]
    assert isinstance(full["roster"], RosterOut) and isinstance(full["timeline"], TimelineOut)
    assert isinstance(full["facts"], FactsOut)


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
        replay(3, "short", pack, "placement")
    with pytest.raises(ValueError, match="unknown override"):
        replay(
            3, "short", pack, override={"placement": replay(3, "short", pack, "roster")["roster"]}
        )
    roster = replay(3, "short", pack, "roster")["roster"]
    with pytest.raises(TypeError, match="truth override must be a TruthOut"):
        replay(3, "short", pack, override={"truth": roster})
    with pytest.raises(TypeError, match="timeline override must be a TimelineOut"):
        replay(3, "short", pack, override={"timeline": roster})


def test_the_fold_gives_what_calling_the_stages_one_by_one_gives():
    from tests.generate.helpers import facts_of, stages

    pack = castle()
    for preset in ("short", "standard", "long"):
        ctx = GenContext.of(pack, 8, preset)
        roster, truth, timeline = stages(ctx)
        _, _, facts = facts_of(ctx)
        full = replay(8, preset, pack)
        assert (full["roster"], full["truth"], full["timeline"], full["facts"]) == (
            roster,
            truth,
            timeline,
            facts,
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
