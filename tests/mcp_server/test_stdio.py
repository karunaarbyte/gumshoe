"""The server as a real subprocess: the protocol owns stdout, nothing else may write there."""

import json
import subprocess
import sys
import threading

import mcp.types as mcp_types
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


def test_stdout_carries_only_protocol_while_a_game_is_played(tmp_path):
    def message(**fields):
        return json.dumps({"jsonrpc": "2.0", **fields}) + "\n"

    script = (
        message(
            id=1,
            method="initialize",
            params={
                "protocolVersion": mcp_types.LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "raw-pipe", "version": "0"},
            },
        )
        + message(method="notifications/initialized")
        + message(id=2, method="tools/call", params={"name": "new_game", "arguments": {"seed": 1}})
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "gumshoe.mcp_server", "--saves", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timer = threading.Timer(60, proc.kill)  # a hang ends the read below instead of the suite
    timer.start()
    lines: list[str] = []
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(script.encode())
        proc.stdin.flush()  # stdin stays open until the reply is in: EOF would end the server
        for raw in proc.stdout:
            if raw.strip():
                lines.append(raw.decode())
            if '"id":2' in raw.decode().replace(" ", ""):
                break
        proc.stdin.close()
        lines += [raw.decode() for raw in proc.stdout if raw.strip()]
        proc.wait(timeout=30)
    finally:
        timer.cancel()
        proc.kill()
        proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
    parsed = [mcp_types.jsonrpc_message_adapter.validate_json(line) for line in lines]
    assert parsed, "the server wrote nothing to stdout"
    results = {m.id: m.result for m in parsed if isinstance(m, mcp_types.JSONRPCResponse)}
    assert 2 in results, "no new_game reply arrived within 60 s (the server hung or died)"
    assert results[2]["structuredContent"]["brief"]["status"] == "playing"
