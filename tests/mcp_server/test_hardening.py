"""Limits and races: open-game cap, close_game, save-name races, collisions that never end."""

import pytest

import gumshoe.mcp_server.host as host_module
from gumshoe.cases import HandleCollision
from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.saves import SaveExists, SaveFile, path_for, write_save
from tests.mcp_server.helpers import SeqIds
from tests.mcp_server.test_saves import code_of, host_in, played


def test_close_game_forgets_the_game_and_frees_its_slot():
    host = GameHost(ids=SeqIds())
    game = host.new_game(1).game
    assert host.close_game(game).closed == game
    assert code_of(lambda: host.case_brief(game)) == "unknown_game"
    assert code_of(lambda: host.close_game(game)) == "unknown_game"


def test_the_open_game_cap_refuses_a_new_game_until_one_is_closed(monkeypatch):
    monkeypatch.setattr(host_module, "MAX_GAMES", 2)
    host = GameHost(ids=SeqIds())
    first = host.new_game(1).game
    host.new_game(2)
    assert code_of(lambda: host.new_game(3)) == "too_many_games"
    host.close_game(first)
    assert host.new_game(3).brief.status == "playing"


def test_close_game_keeps_the_saved_file(tmp_path):
    host = host_in(tmp_path)
    game, _ = played(host)
    name = host.save_game(game).name
    host.close_game(game)
    assert host.load_game(name).brief.status == "playing"


def test_write_save_never_replaces_an_existing_file(tmp_path):
    host = host_in(tmp_path)
    game, _ = played(host)
    name = host.save_game(game).name
    target = path_for(tmp_path, name)
    before = target.read_bytes()
    save = SaveFile(save_format=1, pack="castle", case="{}", state="{}")
    with pytest.raises(SaveExists):
        write_save(tmp_path, name, save)
    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == [target.name]  # no temp left behind


def test_a_save_name_taken_between_the_check_and_the_write_draws_another(tmp_path):
    host = host_in(tmp_path)
    game, _ = played(host)
    taken = "f" * 16
    path_for(tmp_path, taken).write_text("someone else's save")
    names = iter([taken, "e" * 16])
    host._fresh_name = lambda folder: next(names)  # noqa: SLF001
    assert host.save_game(game).name == "e" * 16
    assert path_for(tmp_path, taken).read_text() == "someone else's save"


def test_endless_handle_collisions_end_in_a_runtime_error_not_a_hang(monkeypatch):
    def always(*_args, **_kwargs):
        raise HandleCollision("again")

    monkeypatch.setattr(host_module, "load_session", always)
    with pytest.raises(RuntimeError, match="collision-free"):
        GameHost(ids=SeqIds()).new_game(1)


def test_a_game_error_still_needs_a_known_code():
    with pytest.raises(ValueError, match="unknown error code"):
        GameError("nope", "x")


def asked(host, game):
    """The host after accusation_questions, so interpret_accusation gets past its first check."""
    host.accusation_questions(game, "Boris did it")
    return host


def started():
    host = GameHost(ids=SeqIds())
    new = host.new_game(1)
    return host, new.game, new.brief.suspects[0].handle


@pytest.mark.parametrize(
    "call",
    [
        lambda h, g, s: h.case_brief(["x"]),
        lambda h, g, s: h.close_game(None),
        lambda h, g, s: h.new_game(1, ["standard"]),
        lambda h, g, s: h.new_game(1, "standard", {"pack": "castle"}),
        lambda h, g, s: h.search(g, ["a"]),
        lambda h, g, s: h.interrogate(g, 5),
        lambda h, g, s: h.check_records(g, ["a"]),
        lambda h, g, s: h.check_records(g, s, ["kind"]),
        lambda h, g, s: h.nameable(g, ["who"]),
        lambda h, g, s: h.describe_accusation(g, 5),
        lambda h, g, s: h.accuse(g, s, None, "x"),
        lambda h, g, s: h.accuse(g, s, "x", "y", confirmed="yes"),
        lambda h, g, s: h.persona_brief(g, {"h": 1}),
        lambda h, g, s: h.accusation_questions(g, None),
        lambda h, g, s: h.check_reply(g, s, None, "hi"),
        lambda h, g, s: h.check_reply(g, s, "hi", 7),
        lambda h, g, s: h.check_reply(g, ["s"], "hi", "hello"),
        lambda h, g, s: asked(h, g).interpret_accusation(g, {"who": {"A": "0.9"}}),
        lambda h, g, s: asked(h, g).interpret_accusation(g, {"who": [1, 2]}),
        lambda h, g, s: asked(h, g).interpret_accusation(g, {"who": {"A": True}}),
        lambda h, g, s: asked(h, g).interpret_accusation(g, ["who"]),
        lambda h, g, s: h.save_game(["g"]),
    ],
)
def test_a_wrongly_typed_argument_is_a_bad_argument_not_a_crash(call):
    host, game, suspect = started()
    assert code_of(lambda: call(host, game, suspect)) == "bad_argument"


def test_a_full_host_refuses_a_new_game_before_generating_it(monkeypatch):
    monkeypatch.setattr(host_module, "MAX_GAMES", 1)
    host = GameHost(ids=SeqIds())
    host.new_game(1)
    made: list[int] = []

    def counting(seed, preset, pack):
        made.append(seed)
        raise AssertionError("generated a case for a host that is full")

    monkeypatch.setattr(host_module, "generate_case", counting)
    assert code_of(lambda: host.new_game(2)) == "too_many_games"
    assert made == []


def test_a_full_host_refuses_a_load_before_rebuilding_the_case(tmp_path, monkeypatch):
    host = host_in(tmp_path)
    game, _ = played(host)
    name = host.save_game(game).name
    monkeypatch.setattr(host_module, "MAX_GAMES", 1)

    def rebuilding(*args, **kwargs):
        raise AssertionError("must not rebuild")

    monkeypatch.setattr(host_module, "regenerate_case", rebuilding)
    assert code_of(lambda: host.load_game(name)) == "too_many_games"
