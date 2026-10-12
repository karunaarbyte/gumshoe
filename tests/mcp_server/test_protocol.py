"""The server through a real MCP client over the in-memory transport."""

import re

import pytest
from mcp.client import Client

from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.tools import build_server
from tests.mcp_server.helpers import SeqIds, castle_case

TOOLS = {
    "new_game", "case_brief", "search", "interrogate", "check_records", "notebook", "nameable",
    "describe_accusation", "accuse", "give_up", "reveal", "persona_brief", "check_reply",
    "save_game", "load_game",
}  # fmt: skip
ERROR = re.compile(r"^Error executing tool \w+: (?P<code>[a-z_]+): (?P<message>.+)$", re.DOTALL)


def new_client(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    return host, Client(build_server(host))


async def call(client, tool, /, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def error_of(client, tool, /, **arguments):
    result = await client.call_tool(tool, arguments)
    assert result.is_error
    return result.content[0].text


async def test_the_server_lists_exactly_the_documented_tools_with_descriptions(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        listed = (await client.list_tools()).tools
    assert {t.name for t in listed} == TOOLS
    assert all(t.description for t in listed)
    by_name = {t.name: t for t in listed}
    assert set(by_name["accuse"].input_schema["required"]) == {"game", "who", "how", "why"}
    assert "confirmed" not in by_name["accuse"].input_schema["required"]
    assert by_name["new_game"].input_schema["required"] == ["seed"]


async def explore(client, game, brief):
    for _ in range(6):
        for place in brief["locations"]:
            await call(client, "search", game=game, location=place["handle"])
        for person in brief["suspects"]:
            await call(client, "interrogate", game=game, suspect=person["handle"])
        for item in [*brief["suspects"], *brief["locations"]]:
            await call(client, "check_records", game=game, subject=item["handle"])


async def handle_of(client, game, axis, name):
    options = (await call(client, "nameable", game=game, axis=axis))["options"]
    return next(o["handle"] for o in options if o["name"] == name)


async def truth_handles(client, game, case):
    truth = case.truth
    who = next(s.display_name for s in case.suspects if s.id == truth.who)
    how = next(m.label for m in case.methods if m.id == truth.how)
    why = next(m.label for m in case.motives if m.id == truth.why)
    return (
        await handle_of(client, game, "who", who),
        await handle_of(client, game, "how", how),
        await handle_of(client, game, "why", why),
    )


async def test_a_full_game_is_won_through_the_protocol(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        new = await call(client, "new_game", seed=1)
        game, brief = new["game"], new["brief"]
        await explore(client, game, brief)
        who, how, why = await truth_handles(client, game, castle_case(1))
        plan = await call(client, "describe_accusation", game=game, who=who, how=how, why=why)
        assert plan["can_confirm"]
        pending = await call(client, "accuse", game=game, who=who, how=how, why=why)
        assert pending["status"] == "needs_confirmation" and pending["attempts_left"] == 3
        won = await call(client, "accuse", game=game, who=who, how=how, why=why, confirmed=True)
        assert won["correct"] == 3 and won["game"] == "won"
        assert (await call(client, "reveal", game=game))["culprit"]


async def test_a_full_game_is_lost_through_the_protocol(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        new = await call(client, "new_game", seed=1)
        game, brief = new["game"], new["brief"]
        await explore(client, game, brief)
        who, how, why = await truth_handles(client, game, castle_case(1))
        options = (await call(client, "nameable", game=game, axis="who"))["options"]
        wrongs = [o["handle"] for o in options if o["handle"] != who][:3]
        for handle in wrongs:
            last = await call(
                client, "accuse", game=game, who=handle, how=how, why=why, confirmed=True
            )
        assert last["game"] == "lost" and last["correct"] == 2
        assert "culprit" in await call(client, "reveal", game=game)


async def test_persona_reply_save_and_load_work_through_the_protocol(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        new = await call(client, "new_game", seed=2)
        game, brief = new["game"], new["brief"]
        suspect = brief["suspects"][0]["handle"]
        assert (await call(client, "persona_brief", game=game, suspect=suspect))["says"] == []
        await call(client, "interrogate", game=game, suspect=suspect)
        assert (await call(client, "persona_brief", game=game, suspect=suspect))["says"]
        check = await call(
            client, "check_reply", game=game, suspect=suspect, player_text="Well?", reply="Hm."
        )
        assert check["ok"] is True
        ref = await call(client, "save_game", game=game)
        loaded = await call(client, "load_game", name=ref["name"])
        assert loaded["game"] != game and loaded["brief"]["status"] == "playing"


async def test_a_game_error_is_an_error_result_ending_in_code_and_message(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        text = await error_of(client, "case_brief", game="0000000000000099")
    match = ERROR.match(text)
    assert match and match["code"] == "unknown_game" and match["message"] == "no such game"


async def test_every_error_code_the_host_raises_crosses_the_wire_intact(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        game = (await call(client, "new_game", seed=1))["game"]
        cases = [
            (await error_of(client, "new_game", seed=-1), "bad_argument"),
            (await error_of(client, "nameable", game=game, axis="when"), "bad_argument"),
            (await error_of(client, "reveal", game=game), "not_over"),
            (await error_of(client, "persona_brief", game=game, suspect="h_x"), "unknown_handle"),
            (await error_of(client, "load_game", name="0" * 16), "bad_save"),
        ]
        await call(client, "give_up", game=game)
        cases.append((await error_of(client, "give_up", game=game), "game_over"))
    for text, code in cases:
        match = ERROR.match(text)
        assert match and match["code"] == code, text


async def test_a_wrongly_typed_argument_is_an_error_result_not_a_crash(tmp_path):
    _, client = new_client(tmp_path)
    async with client:
        text = await error_of(client, "new_game", seed="seven")
        assert text.startswith("Error executing tool new_game")
        assert (await call(client, "new_game", seed=1))["game"]  # the server is still fine


async def test_an_unexpected_exception_reveals_nothing(tmp_path, monkeypatch):
    host, client = new_client(tmp_path)

    def broken(game):
        raise RuntimeError("secret skeleton detail f_deadbeef")

    monkeypatch.setattr(host, "notebook", broken)
    async with client:
        game = (await call(client, "new_game", seed=1))["game"]
        text = await error_of(client, "notebook", game=game)
    assert text == "Error executing tool notebook"


def test_game_error_text_is_code_colon_message():
    assert str(GameError("bad_save", "nope")) == "bad_save: nope"


@pytest.mark.parametrize("preset", ["short", "standard", "long"])
async def test_every_preset_starts_through_the_protocol(tmp_path, preset):
    _, client = new_client(tmp_path)
    async with client:
        new = await call(client, "new_game", seed=3, preset=preset)
    assert new["brief"]["status"] == "playing" and new["brief"]["suspects"]
