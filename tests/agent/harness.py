"""Shared test pieces for the agent: a real GameHost behind an in-process MCP client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.client import Client

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.deps import Deps, TurnContext
from gumshoe.agent.events import TurnEvent
from gumshoe.agent.game import GameClient
from gumshoe.agent.turn import take_turn
from gumshoe.cases import PlayerCaseView
from gumshoe.mcp_server import GameHost
from gumshoe.mcp_server.tools import build_server
from tests.agent.fakes import Script, ScriptedDecider, ScriptedLlm
from tests.mcp_server.helpers import SeqIds


@dataclass
class Harness:
    host: GameHost
    deps: Deps
    ctx: TurnContext
    brief: PlayerCaseView
    script: Script
    decider: ScriptedDecider
    llm: ScriptedLlm


@asynccontextmanager
async def raw_client(host: GameHost) -> AsyncIterator[GameClient]:
    async with Client(build_server(host)) as client:
        yield GameClient(client)


@asynccontextmanager
async def playing(
    script: Script,
    llm: ScriptedLlm | None = None,
    *,
    seed: int = 1,
    preset: str = "standard",
    config: AgentConfig | None = None,
) -> AsyncIterator[Harness]:
    """Start a game and yield everything a turn needs. Use `async with` inside the test itself
    (the SDK client owns a task group, so it must not be opened in a pytest fixture)."""
    host = GameHost(ids=SeqIds())
    async with raw_client(host) as client:
        new = await client.new_game(seed, preset)
        decider = ScriptedDecider(script)
        the_llm = llm or ScriptedLlm([])
        deps = Deps(client=client, decider=decider, llm=the_llm, config=config or AgentConfig())
        yield Harness(host, deps, TurnContext(game=new.game), new.brief, script, decider, the_llm)


async def turn(h: Harness, text: str) -> list[TurnEvent]:
    return [event async for event in take_turn(h.deps, h.ctx, text)]
