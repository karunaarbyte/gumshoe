import pytest
from mcp.client import Client
from mcp.types import CallToolResult, TextContent

from gumshoe.agent.game import CODES, INTERNAL, GameClient, ToolFailure
from gumshoe.mcp_server import GameHost
from gumshoe.mcp_server.errors import CODES as SERVER_CODES
from gumshoe.mcp_server.tools import build_server
from tests.mcp_server.helpers import SeqIds


def test_the_agents_copy_of_the_error_codes_equals_the_servers():
    assert set(CODES) == set(SERVER_CODES)


async def test_a_typed_round_trip_over_the_in_process_client():
    host = GameHost(ids=SeqIds())
    async with Client(build_server(host)) as raw:
        client = GameClient(raw)
        new = await client.new_game(1)
        assert new.brief.status == "playing" and new.brief.locations
        brief = await client.case_brief(new.game)
        assert brief == new.brief
        result = await client.search(new.game, brief.locations[0].handle)
        assert result.kind == "search"
        notebook = await client.notebook(new.game)
        assert notebook.sections is not None
        questions = await client.accusation_questions(new.game, "the cook did it")
        assert set(questions.questions) == {"who"}
        await client.close_game(new.game)


async def test_a_game_error_becomes_a_tool_failure_with_its_code():
    host = GameHost(ids=SeqIds())
    async with Client(build_server(host)) as raw:
        client = GameClient(raw)
        with pytest.raises(ToolFailure) as err:
            await client.case_brief("nope")
        assert err.value.code == "unknown_game"
        new = await client.new_game(1)
        with pytest.raises(ToolFailure) as err2:
            await client.reveal(new.game)
        assert err2.value.code == "not_over"


async def test_an_argument_validation_error_or_unknown_tool_is_internal():
    host = GameHost(ids=SeqIds())
    async with Client(build_server(host)) as raw:
        client = GameClient(raw)
        with pytest.raises(ToolFailure) as err:
            await client._call("search", {"game": 5})  # noqa: SLF001  (wrong argument types)
        assert err.value.code == INTERNAL
        with pytest.raises(ToolFailure) as err2:
            await client._call("no_such_tool", {})  # noqa: SLF001
        assert err2.value.code == INTERNAL


async def test_a_bug_inside_a_tool_is_internal_and_leaks_nothing(monkeypatch):
    host = GameHost(ids=SeqIds())

    def broken(game):
        raise RuntimeError("secret skeleton detail f_deadbeef")

    monkeypatch.setattr(host, "notebook", broken)
    async with Client(build_server(host)) as raw:
        client = GameClient(raw)
        new = await client.new_game(1)
        with pytest.raises(ToolFailure) as err:
            await client.notebook(new.game)
        assert err.value.code == INTERNAL and "deadbeef" not in err.value.message


class ErrorText:
    """A stand-in MCP client whose every call fails with the given text."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def call_tool(self, tool, arguments):
        return CallToolResult(content=[TextContent(type="text", text=self.text)], is_error=True)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Error executing tool search: game_over: the game has ended", "game_over"),
        ("Error executing tool search: made_up_code: something", INTERNAL),
        ("Error executing tool search", INTERNAL),
    ],
)
async def test_only_a_known_code_is_trusted(text, code):
    client = GameClient(ErrorText(text))  # type: ignore[arg-type]
    with pytest.raises(ToolFailure) as err:
        await client.notebook("g")
    assert err.value.code == code
