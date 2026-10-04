import pytest

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
    assert isinstance(changed["truth"], TruthOut)
    assert changed["truth"].roster.scene_type == other.scene_type  # type: ignore[attr-defined]
    assert changed["truth"] != base["truth"] and changed["timeline"] != base["timeline"]
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
        override={"truth": other, "roster": replay(5, "short", pack, "roster")["roster"]},
    )
    assert both["roster"] == replay(5, "short", pack, "roster")["roster"]


def test_replay_rejects_unknown_stages_and_wrongly_typed_overrides():
    pack = castle()
    with pytest.raises(ValueError, match="unknown stage"):
        replay(3, "short", pack, "facts")
    with pytest.raises(ValueError, match="unknown override"):
        replay(3, "short", pack, override={"facts": replay(3, "short", pack, "roster")["roster"]})
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
