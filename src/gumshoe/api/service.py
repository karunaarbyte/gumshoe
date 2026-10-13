"""The games the API serves: one conversation record and one lock per game.

A turn runs in a detached task that holds the game's lock, so a second turn on the same game
waits its turn and a dropped client never cancels the work. The reader of a turn only drains a
queue.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from gumshoe.agent import (
    Deps,
    NewGameView,
    SaveView,
    ToolFailure,
    TurnContext,
    TurnEvent,
    take_turn,
)
from gumshoe.agent.events import Done
from gumshoe.cases import NotebookView, PlayerCaseView

logger = logging.getLogger(__name__)

_UNKNOWN = "no such game"


class GameState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    brief: PlayerCaseView
    notebook: NotebookView


@dataclass
class _Slot:
    ctx: TurnContext
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gone: bool = False


@dataclass
class _Reader:
    """Shared by a turn and its reader: set once the client has stopped reading."""

    gone: bool = False


async def _drain(
    queue: "asyncio.Queue[TurnEvent | None]", reader: _Reader
) -> AsyncGenerator[TurnEvent]:
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        reader.gone = True  # a turn still queued for the lock now has nobody to serve


class AgentService:
    def __init__(self, deps: Deps, *, grace_s: float = 5.0) -> None:
        self._deps = deps
        self._grace_s = grace_s
        self._slots: dict[str, _Slot] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _slot(self, game: str) -> _Slot:
        slot = self._slots.get(game)
        if slot is None:
            raise ToolFailure("unknown_game", _UNKNOWN)
        return slot

    def _register(self, view: NewGameView) -> NewGameView:
        self._slots[view.game] = _Slot(TurnContext(game=view.game))
        return view

    async def new_game(self, seed: int, preset: str = "standard") -> NewGameView:
        return self._register(await self._deps.client.new_game(seed, preset))

    async def load_game(self, name: str) -> NewGameView:
        return self._register(await self._deps.client.load_game(name))

    async def state(self, game: str) -> GameState:
        self._slot(game)
        brief = await self._deps.client.case_brief(game)
        notebook = await self._deps.client.notebook(game)
        return GameState(brief=brief, notebook=notebook)

    def start_turn(self, game: str, text: str) -> AsyncGenerator[TurnEvent]:
        slot = self._slot(game)
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        reader = _Reader()
        task = asyncio.create_task(self._run(slot, text, queue, reader))
        self._tasks.add(task)  # a strong reference: the loop only keeps a weak one
        task.add_done_callback(self._finished)
        # The reader's end-of-stream. A done callback runs however the task ended, even when
        # it was cancelled before its first step (a finally block would never be entered).
        task.add_done_callback(lambda _task: queue.put_nowait(None))
        return _drain(queue, reader)

    async def _run(
        self, slot: _Slot, text: str, queue: "asyncio.Queue[TurnEvent | None]", reader: _Reader
    ) -> None:
        async with slot.lock:
            if slot.gone:  # deleted while this turn waited
                queue.put_nowait(Done())
                return
            if reader.gone:  # the client left while this turn waited: do not run it
                return
            async for event in take_turn(self._deps, slot.ctx, text):
                queue.put_nowait(event)

    def _finished(self, task: "asyncio.Task[None]") -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("a turn task died", exc_info=error)

    async def save_game(self, game: str) -> SaveView:
        slot = self._slot(game)
        async with slot.lock:  # wait for a running turn: the save is a clean state
            if slot.gone:
                raise ToolFailure("unknown_game", _UNKNOWN)
            return await self._deps.client.save_game(game)

    async def delete_game(self, game: str) -> None:
        slot = self._slot(game)
        async with slot.lock:  # never orphan a running turn
            if slot.gone:
                raise ToolFailure("unknown_game", _UNKNOWN)
            try:
                await self._deps.client.close_game(game)
            except ToolFailure as exc:
                if exc.code != "unknown_game":
                    raise  # the host may still hold the game: keep the slot, DELETE can retry
            slot.gone = True
            self._slots.pop(game, None)

    async def idle(self) -> None:
        """Wait until every running or queued turn has finished."""
        # Wait on the unfinished tasks only: a finished task stays in `_tasks` until its done
        # callback runs, and gather() over finished tasks returns without yielding (3.12+), so
        # looping on `self._tasks` would spin and starve that very callback.
        while pending := [task for task in self._tasks if not task.done()]:
            await asyncio.wait(pending)

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self._grace_s)
