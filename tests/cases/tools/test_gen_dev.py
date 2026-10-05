import pytest

from gumshoe.cases.generate import timeline as timeline_stage
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import RosterOut, TimelineOut, TruthOut
from gumshoe.cases.tools.builtin import load_builtin_pack
from gumshoe.cases.tools.gen_dev import replay


def castle():
    return load_builtin_pack("castle")


def test_replay_returns_every_stage_up_to_the_requested_one():
    pack = castle()
    assert list(replay(3, "short", pack, "roster")) == ["roster"]
    assert list(replay(3, "short", pack, "truth")) == ["roster", "truth"]
    full = replay(3, "short", pack)
    assert list(full) == ["roster", "truth", "timeline"]
    assert isinstance(full["roster"], RosterOut) and isinstance(full["timeline"], TimelineOut)


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
    from gumshoe.cases.generate.gen_context import GenContext
    from tests.generate.helpers import stages

    pack = castle()
    for preset in ("short", "standard", "long"):
        ctx = GenContext.of(pack, 8, preset)
        roster, truth, timeline = stages(ctx)
        full = replay(8, preset, pack)
        assert (full["roster"], full["truth"], full["timeline"]) == (roster, truth, timeline)


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
