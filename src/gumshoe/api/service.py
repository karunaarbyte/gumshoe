"""The games the API serves: one conversation record and one lock per game.

A turn runs in a detached task that holds the game's lock, so a dropped client never cancels the
work. One turn at a time per game: a second one while the first runs is refused with 409
`turn_in_progress` (each turn is billed, so they are never queued). Save and delete wait for the
lock. The reader of a turn only drains a queue.
"""

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gumshoe.agent import (
    Deps,
    NewGameView,
    SaveView,
    ToolFailure,
    TurnContext,
    TurnEvent,
    take_confirm,
    take_turn,
)
from gumshoe.agent.events import Clarify, Done
from gumshoe.api.errors import ApiError
from gumshoe.cases import NotebookView, PlayerCaseView, RevealView
from gumshoe.decider import describe_failure

logger = logging.getLogger(__name__)

_UNKNOWN = "no such game"
SHUTTING_DOWN = "The game server is shutting down. Please try again in a moment."
MAX_TURNS_KEPT = 200  # per game, for the transcript; the oldest are dropped first


Outcome = Literal["playing", "won", "lost", "gave_up"]


class PendingView(BaseModel):
    """The confirmation waiting for the player's answer, so a reloaded page can show it again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_id: str
    kind: Literal["accuse", "give_up"]
    text: str
    warnings: tuple[str, ...]


class GameState(BaseModel):
    """Everything a UI needs to draw a game after a reload (the chat comes from `turns`). No
    seed: a seed is the whole case, so whoever holds it can replay the game and give up to read
    the answer. The preset is known only for games made here (a load does not say)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief: PlayerCaseView
    notebook: NotebookView
    outcome: Outcome
    pending: PendingView | None
    reveal: RevealView | None  # only once the game is over
    preset: str | None


class GameSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    game: str
    preset: str | None
    outcome: Outcome
    attempts_left: int
    turn_running: bool


class SaveSummary(BaseModel):
    """A save as a list shows it. Never its case: a save file holds the whole truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    created_at: str  # UTC, ISO 8601
    pack: str
    status: Literal["playing", "won", "lost"]


class TurnRecord(BaseModel):
    """One turn as the player saw it, for a UI that reloads. Lives in memory with the game."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    kind: Literal["turn", "confirm"]  # typed text, or the confirm button
    text: str  # what the player typed, or the button's yes / no
    ts: str  # when the turn started (UTC, ISO 8601)
    events: list[TurnEvent]
    complete: bool  # false while the turn is still running


def _transcript() -> "deque[TurnRecord]":
    return deque(maxlen=MAX_TURNS_KEPT)


@dataclass
class _Slot:
    ctx: TurnContext
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gone: bool = False
    busy: bool = False  # a turn is running or waiting for the lock: the next one is refused
    turns: "deque[TurnRecord]" = field(default_factory=_transcript)
    preset: str | None = None  # None for a loaded game


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
        reader.gone = True  # a turn still waiting for the lock now has nobody to serve


class AgentService:
    def __init__(
        self,
        deps: Deps,
        *,
        grace_s: float = 5.0,
        list_saves: Callable[[], list[SaveSummary]] | None = None,
    ) -> None:
        self._deps = deps
        self._grace_s = grace_s
        self._list_saves = list_saves  # blocking file reads: called in a worker thread
        self._slots: dict[str, _Slot] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _slot(self, game: str) -> _Slot:
        slot = self._slots.get(game)
        if slot is None:
            raise ToolFailure("unknown_game", _UNKNOWN)
        return slot

    def _register(self, view: NewGameView, preset: str | None) -> NewGameView:
        self._slots[view.game] = _Slot(TurnContext(game=view.game), preset=preset)
        return view

    async def new_game(self, seed: int, preset: str = "standard") -> NewGameView:
        return self._register(await self._deps.client.new_game(seed, preset), preset)

    async def load_game(self, name: str) -> NewGameView:
        return self._register(await self._deps.client.load_game(name), None)

    @staticmethod
    def _outcome(slot: _Slot, brief: PlayerCaseView) -> Outcome:
        if brief.status == "playing":
            return "playing"
        if slot.ctx.outcome is not None:  # the engine cannot tell a give-up from a loss
            return slot.ctx.outcome
        return "won" if brief.status == "won" else "lost"

    async def state(self, game: str) -> GameState:
        slot = self._slot(game)
        brief = await self._deps.client.case_brief(game)
        notebook = await self._deps.client.notebook(game)
        outcome = self._outcome(slot, brief)
        reveal = None if outcome == "playing" else await self._deps.client.reveal(game)
        pending = slot.ctx.pending
        return GameState(
            brief=brief,
            notebook=notebook,
            outcome=outcome,
            pending=None
            if pending is None
            else PendingView(
                pending_id=pending.id,
                kind=pending.kind,
                text=pending.line,
                warnings=pending.warnings,
            ),
            reveal=reveal,
            preset=slot.preset,
        )

    async def games(self) -> list[GameSummary]:
        """The open games, oldest first."""
        found = []
        for game, slot in list(self._slots.items()):
            try:
                brief = await self._deps.client.case_brief(game)
            except ToolFailure as exc:
                if exc.code == "unknown_game":
                    continue  # deleted meanwhile
                raise
            found.append(
                GameSummary(
                    game=game,
                    preset=slot.preset,
                    outcome=self._outcome(slot, brief),
                    attempts_left=brief.attempts_left,
                    turn_running=slot.busy,
                )
            )
        return found

    async def saves(self) -> list[SaveSummary]:
        if self._list_saves is None:
            return []
        return await asyncio.to_thread(self._list_saves)

    def turns(self, game: str) -> list[TurnRecord]:
        """The game's transcript, oldest first; a running turn is the last, not yet complete."""
        return list(self._slot(game).turns)

    def start_turn(
        self, game: str, text: str, *, pending_id: str | None = None
    ) -> AsyncGenerator[TurnEvent]:
        """Raises at once (before any streaming) for an unknown game or a turn in progress."""
        slot = self._slot(game)
        return self._start(
            slot,
            lambda: take_turn(self._deps, slot.ctx, text, pending_id=pending_id),
            kind="turn",
            text=text,
        )

    def start_confirm(
        self, game: str, pending_id: str, answer: Literal["yes", "no"]
    ) -> AsyncGenerator[TurnEvent]:
        """The confirm button. Raises at once for an unknown game, a turn in progress, or a
        confirmation that is not the one waiting (409 `no_such_pending`)."""
        slot = self._slot(game)
        self._ensure_free(slot)
        pending = slot.ctx.pending
        if pending is None or pending.id != pending_id:
            raise ApiError(409, "no_such_pending", "that confirmation is not waiting any more")
        return self._start(
            slot,
            lambda: take_confirm(self._deps, slot.ctx, pending_id, answer),
            kind="confirm",
            text=answer,
        )

    @staticmethod
    def _ensure_free(slot: _Slot) -> None:
        if slot.busy:
            raise ApiError(
                409, "turn_in_progress", "a turn is already running for this game; wait for it"
            )

    def _start(
        self,
        slot: _Slot,
        events: Callable[[], AsyncIterator[TurnEvent]],
        *,
        kind: Literal["turn", "confirm"],
        text: str,
    ) -> AsyncGenerator[TurnEvent]:
        self._ensure_free(slot)
        slot.busy = True
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        reader = _Reader()
        record = TurnRecord(
            turn_id=uuid.uuid4().hex,
            kind=kind,
            text=text,
            ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
            events=[],
            complete=False,
        )
        task = asyncio.create_task(self._run(slot, events, queue, reader, record))
        self._tasks.add(task)  # a strong reference: the loop only keeps a weak one
        task.add_done_callback(self._finished)
        # Done callbacks run in order and however the task ended, even when it was cancelled
        # before its first step (a finally block would never be entered): free the game first,
        # then end the reader's stream, so a client that saw the end can start the next turn.
        task.add_done_callback(lambda _task: setattr(slot, "busy", False))
        task.add_done_callback(lambda _task: queue.put_nowait(None))
        return _drain(queue, reader)

    async def _run(
        self,
        slot: _Slot,
        events: Callable[[], AsyncIterator[TurnEvent]],
        queue: "asyncio.Queue[TurnEvent | None]",
        reader: _Reader,
        record: TurnRecord,
    ) -> None:
        def emit(event: TurnEvent) -> None:
            record.events.append(event)
            queue.put_nowait(event)

        try:
            async with slot.lock:
                if slot.gone:  # deleted while this turn waited
                    queue.put_nowait(Done())
                    return
                if reader.gone:  # the client left while this turn waited: do not run it
                    return
                slot.turns.append(record)  # only turns that really run are kept
                async for event in events():
                    emit(event)
        except asyncio.CancelledError:
            # shutdown: tell the client, so it can tell this from a dropped connection
            emit(Clarify(reason="error", text=SHUTTING_DOWN))
            emit(Done())
            raise
        finally:
            record.complete = True

    def _finished(self, task: "asyncio.Task[None]") -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("a turn task died: %s", describe_failure(error))

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

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self._grace_s)
