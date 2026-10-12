import pytest

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
