import pytest

import gumshoe.cases.play.session as session_module
from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.host import RandomIds
from tests.mcp_server.helpers import SeqIds, make_host


def test_new_game_returns_an_id_and_the_opening_brief():
    host = make_host()
    new = host.new_game(1)
    assert new.game == "0000000000000002"  # the salt took the first id
    assert new.brief.status == "playing" and new.brief.attempts_left == 3
    assert new.brief.intro and new.brief.suspects and new.brief.locations
    assert host.case_brief(new.game) == new.brief


def test_identical_calls_with_pinned_ids_give_identical_output():
    first = make_host().new_game(7, "short")
    second = make_host().new_game(7, "short")
    assert first == second
    assert first != make_host().new_game(8, "short")


def test_each_game_gets_its_own_salt_so_handles_differ():
    host = make_host()
    a, b = host.new_game(3), host.new_game(3)
    assert a.game != b.game
    assert a.brief.locations[0].handle != b.brief.locations[0].handle


@pytest.mark.parametrize("seed", [True, -1, 2**63, 1.5, "7", None])
def test_a_bad_seed_is_a_bad_argument(seed):
    with pytest.raises(GameError) as err:
        make_host().new_game(seed)
    assert err.value.code == "bad_argument"


def test_the_largest_allowed_seed_works():
    assert make_host().new_game(2**63 - 1).brief.status == "playing"


@pytest.mark.parametrize("preset", ["", "epic", "Standard"])
def test_an_unsupported_preset_is_a_bad_argument(preset):
    with pytest.raises(GameError) as err:
        make_host().new_game(1, preset)
    assert err.value.code == "bad_argument" and "castle" in err.value.message


@pytest.mark.parametrize("pack", ["nowhere", "../castle", "", "castle.toml"])
def test_an_unknown_pack_is_a_bad_argument(pack):
    with pytest.raises(GameError) as err:
        make_host().new_game(1, pack=pack)
    assert err.value.code == "bad_argument"


def test_an_unknown_game_is_reported_as_such():
    with pytest.raises(GameError) as err:
        make_host().case_brief("0000000000000099")
    assert err.value.code == "unknown_game"


def test_an_unknown_error_code_cannot_be_made():
    with pytest.raises(ValueError):
        GameError("oops", "nope")


def test_a_handle_collision_draws_the_next_salt(monkeypatch):
    real = session_module._make_handles
    salts: list[str] = []

    def flaky(case, salt):
        salts.append(salt)
        if len(salts) == 1:
            raise session_module.HandleCollision("forced")
        return real(case, salt)

    monkeypatch.setattr(session_module, "_make_handles", flaky)
    new = GameHost(ids=SeqIds()).new_game(1)
    assert salts == ["0000000000000001", "0000000000000002"]
    assert new.game == "0000000000000003" and new.brief.status == "playing"


def test_a_repeated_game_id_is_skipped_and_the_first_game_survives():
    class Repeating:
        def __init__(self):
            self.values = iter(["a" * 16, "b" * 16, "a" * 16, "c" * 16, "d" * 16, "e" * 16])

        def next(self):
            return next(self.values)

    host = GameHost(ids=Repeating())
    first = host.new_game(1)
    second = host.new_game(2)
    assert first.game != second.game
    assert host.case_brief(first.game).status == "playing"
    assert host.case_brief(second.game).status == "playing"


def test_the_default_id_source_gives_16_lowercase_hex_characters():
    value = RandomIds().next()
    assert len(value) == 16 and value == value.lower() and int(value, 16) >= 0
    assert RandomIds().next() != value


def test_close_ref_is_exported_with_the_other_views():
    import gumshoe.mcp_server as server

    host = make_host()
    closed = host.close_game(host.new_game(1).game)
    assert "CloseRef" in server.__all__ and isinstance(closed, server.CloseRef)


def test_the_instructions_say_that_a_seed_is_the_whole_case():
    from gumshoe.mcp_server.tools import INSTRUCTIONS

    assert "A seed is the whole case" in INSTRUCTIONS
    assert "gives up sees its truth" in INSTRUCTIONS
