import pytest

from gumshoe.cases import load_builtin_pack
from gumshoe.mcp_server import GameError
from tests.mcp_server.helpers import castle_case, explore_all, make_host

SEED = 1


def started():
    host = make_host()
    new = host.new_game(SEED)
    return host, new.game, new.brief


def test_persona_brief_through_the_host_is_empty_then_holds_the_interrogation():
    host, game, brief = started()
    suspect = brief.suspects[0]
    assert host.persona_brief(game, suspect.handle).says == ()
    result = host.interrogate(game, suspect.handle)
    assert len(host.persona_brief(game, suspect.handle).says) == len(result.new_facts)


@pytest.mark.parametrize("handle", ["", "h_nothing"])
def test_an_unknown_suspect_handle_is_unknown_handle(handle):
    host, game, _ = started()
    with pytest.raises(GameError) as err:
        host.persona_brief(game, handle)
    assert err.value.code == "unknown_handle"


def test_a_location_handle_is_unknown_handle():
    host, game, brief = started()
    with pytest.raises(GameError) as err:
        host.persona_brief(game, brief.locations[0].handle)
    assert err.value.code == "unknown_handle"


def test_persona_brief_on_an_unknown_game_is_unknown_game():
    with pytest.raises(GameError) as err:
        make_host().persona_brief("0000000000000099", "h_x")
    assert err.value.code == "unknown_game"


def test_the_brief_is_available_after_the_end():
    host, game, brief = started()
    host.give_up(game)
    assert host.persona_brief(game, brief.suspects[0].handle).name


def test_a_plain_reply_passes_the_check():
    host, game, brief = started()
    check = host.check_reply(game, brief.suspects[0].handle, "Where were you?", "I was busy.")
    assert check.ok and check.violations == ()


def test_a_reply_naming_a_method_the_player_has_not_met_is_flagged_by_axis_only():
    host, game, brief = started()
    case = castle_case(SEED)
    label = next(m.label for m in case.methods if m.id == case.truth.how)
    check = host.check_reply(game, brief.suspects[0].handle, "Tell me more.", f"It was {label}!")
    assert not check.ok
    assert {v.category for v in check.violations} == {"how"}
    assert label not in check.model_dump_json()


def test_a_method_the_case_left_out_is_flagged_exactly_like_one_it_holds():
    host, game, brief = started()
    case = castle_case(SEED)
    held_types = {m.type for m in case.methods}
    pack = load_builtin_pack("castle")
    inside = next(d.label for d in pack.method_defs if d.key in held_types)
    outside = next(d.label for d in pack.method_defs if d.key not in held_types)
    suspect = brief.suspects[0].handle
    verdicts = [host.check_reply(game, suspect, "", f"It was {w}.") for w in (inside, outside)]
    assert verdicts[0] == verdicts[1]
    assert not verdicts[0].ok


@pytest.mark.parametrize(("seed", "preset"), [(7, "standard"), (2, "short"), (3, "long")])
def test_check_reply_cannot_tell_which_methods_and_motives_are_in_play(seed, preset):
    """Every form of every pack method and motive gets the same verdict on a fresh game: its
    own axis, once. So probing the check reveals nothing about the hidden candidate set."""
    host = make_host()
    new = host.new_game(seed, preset)
    pack = load_builtin_pack("castle")
    suspect = new.brief.suspects[0].handle
    for axis, defs in (("how", pack.method_defs), ("why", pack.motive_defs)):
        for d in defs:
            for form in (d.label, *d.aliases):
                check = host.check_reply(new.game, suspect, "", f"It was {form}.")
                assert [(v.category, v.count) for v in check.violations] == [(axis, 1)], form


def test_the_flagged_word_is_allowed_once_the_player_says_it_first():
    host, game, brief = started()
    case = castle_case(SEED)
    label = next(m.label for m in case.methods if m.id == case.truth.how)
    check = host.check_reply(game, brief.suspects[0].handle, f"{label}?", f"It was {label}!")
    assert check.ok


def test_check_reply_for_an_unknown_suspect_is_unknown_handle_like_persona_brief():
    host, game, _ = started()
    with pytest.raises(GameError) as err:
        host.check_reply(game, "h_nothing", "hi", "hello")
    assert err.value.code == "unknown_handle"


@pytest.mark.parametrize("which", ["player_text", "reply"])
def test_text_longer_than_the_limit_is_a_bad_argument(which):
    host, game, brief = started()
    long = "x" * 4001
    texts = {"player_text": "hi", "reply": "hi"} | {which: long}
    with pytest.raises(GameError) as err:
        host.check_reply(game, brief.suspects[0].handle, texts["player_text"], texts["reply"])
    assert err.value.code == "bad_argument"
    host.check_reply(game, brief.suspects[0].handle, "x" * 4000, "y" * 4000)


def test_check_reply_works_after_the_end_and_on_unknown_games():
    host, game, brief = started()
    explore_all(host, game)
    host.give_up(game)
    assert host.check_reply(game, brief.suspects[0].handle, "hi", "hello").ok
    with pytest.raises(GameError) as err:
        host.check_reply("0000000000000099", "h_x", "hi", "hello")
    assert err.value.code == "unknown_game"
