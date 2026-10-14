"""Shared pieces for the API tests: the service over a real host and scripted fakes."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gumshoe.agent import AgentConfig, Deps
from gumshoe.api.service import AgentService
from gumshoe.decider import DecisionResult, Question
from gumshoe.mcp_server import GameHost
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script, ScriptedDecider, ScriptedLlm
from tests.agent.harness import raw_client
from tests.mcp_server.helpers import SeqIds


class GatedDecider(ScriptedDecider):
    """Holds every decide() call until `release` is set; `started` counts the calls that began."""

    def __init__(self, script: Script) -> None:
        super().__init__(script)
        self.started = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        self.started += 1
        self.entered.set()
        await self.release.wait()
        return await super().decide(state, questions, node=node, decision_id=decision_id)


@dataclass
class Served:
    service: AgentService
    host: GameHost
    decider: ScriptedDecider
    script: Script


@asynccontextmanager
async def serving(
    script: Script,
    llm: ScriptedLlm | None = None,
    *,
    decider: ScriptedDecider | None = None,
    saves_dir: Path | None = None,
    grace_s: float = 5.0,
) -> AsyncIterator[Served]:
    """A service over a real GameHost (pinned ids) behind an in-process MCP client. Use
    `async with` inside the test (the SDK client owns a task group)."""
    host = GameHost(ids=SeqIds(), saves_dir=saves_dir)
    async with raw_client(host) as client:
        the_decider = decider or ScriptedDecider(script)
        deps = Deps(
            client=client,
            decider=the_decider,
            llm=llm or ScriptedLlm([]),
            config=AgentConfig(),
        )
        service = AgentService(deps, grace_s=grace_s)
        try:
            yield Served(service, host, the_decider, script)
        finally:
            await service.aclose()


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """The (event name, data) pairs of an SSE body; fails on a malformed block."""
    pairs: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):  # blank, or a keep-alive comment
            continue
        lines = block.split("\n")
        assert len(lines) == 2, f"bad SSE block: {block!r}"
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
        pairs.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return pairs


def fake_factory(
    script: Script, llm: ScriptedLlm | None = None, *, saves_dir: Path | None = None
) -> Callable[[SqliteStatsStore], AbstractAsyncContextManager[AgentService]]:
    @asynccontextmanager
    async def factory(store: SqliteStatsStore) -> AsyncIterator[AgentService]:
        async with serving(script, llm, saves_dir=saves_dir) as served:
            yield served.service

    return factory


async def idle(service: AgentService) -> None:
    """Wait until every turn the service started has finished."""
    while pending := [task for task in service._tasks if not task.done()]:
        await asyncio.wait(pending)


class HeldSave:
    """Make the service's next save hold the game's lock until `release` is set."""

    def __init__(self, monkeypatch, service: AgentService) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        client = service._deps.client
        real = client.save_game

        async def save_game(game):
            self.entered.set()
            await self.release.wait()
            return await real(game)

        monkeypatch.setattr(client, "save_game", save_game)
