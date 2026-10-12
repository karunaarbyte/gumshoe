"""The server as a real subprocess: the protocol owns stdout, nothing else may write there."""

import subprocess
import sys

from mcp import StdioServerParameters
from mcp.client import Client

from tests.mcp_server.test_protocol import TOOLS


def run(*args, stdin=b""):
    return subprocess.run(
        [sys.executable, *args], input=stdin, capture_output=True, timeout=120, check=False
    )


def test_importing_the_server_prints_nothing_to_stdout():
    done = run("-c", "import gumshoe.cases, gumshoe.mcp_server, gumshoe.mcp_server.tools")
    assert done.returncode == 0 and done.stdout == b""


def test_a_server_whose_client_closes_stdin_exits_cleanly_with_empty_stdout():
    done = run("-m", "gumshoe.mcp_server")
    assert done.returncode == 0 and done.stdout == b""


def test_help_lists_the_saves_option():
    done = run("-m", "gumshoe.mcp_server", "--help")
    assert done.returncode == 0 and b"--saves" in done.stdout


async def test_a_stdio_client_lists_the_tools_starts_a_game_and_saves_it(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "gumshoe.mcp_server", "--saves", str(tmp_path)]
    )
    async with Client(params) as client:
        listed = (await client.list_tools()).tools
        assert {t.name for t in listed} == TOOLS
        new = await client.call_tool("new_game", {"seed": 4})
        assert not new.is_error and new.structured_content["brief"]["status"] == "playing"
        saved = await client.call_tool("save_game", {"game": new.structured_content["game"]})
        assert not saved.is_error
    assert len(list(tmp_path.glob("*.json"))) == 1
