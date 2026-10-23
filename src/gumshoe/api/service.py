"""The games the API serves: one conversation record and one lock per game.

A turn runs in a detached task that holds the game's lock, so a dropped client never cancels the
work. One turn at a time per game: a second one while the first runs is refused with 409
`turn_in_progress` (each turn is billed, so they are never queued). Save and delete wait for the
lock. The reader of a turn only drains a queue.

The limits: open games per session and per IP, turns in flight per session and per IP, the
creation and turn rates (`Quotas`), and the gate (`TurnGate`) that caps the turns processed at
once across every game. A turn waiting on its game's lock (for example behind a long save) still
counts in `gate.queued`, but it never holds a running place. Every place a refused, finished,
failed or abandoned turn held is given back exactly once (the task's done callbacks).
"""

import asyncio
import hmac
import logging
import uuid
from collections import Counter, deque
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
from gumshoe.agent.events import Clarify, Done, Queued
from gumshoe.api.errors import BAD_SAVE_MESSAGE, UNKNOWN_GAME, ApiError
from gumshoe.api.ratelimit import Busy, Quotas, Ticket, TurnGate
from gumshoe.api.saveowners import SaveOwners
from gumshoe.cases import NotebookView, PlayerCaseView, RevealView
from gumshoe.config import Settings
from gumshoe.decider import describe_failure

logger = logging.getLogger(__name__)

SHUTTING_DOWN = "The game server is shutting down. Please try again in a moment."
BUSY_TEXT = "The detectives are busy right now. Please try again in a moment."
MAX_TURNS_KEPT = 200  # per game, for the transcript; the oldest are dropped first


Outcome = Literal["playing", "won", "lost", "gave_up"]


@dataclass(frozen=True)
class Caps:
    """How much one session or one IP may hold at once. 0 = unlimited."""

    games_per_session: int = 0
    games_per_ip: int = 0
    turns_per_session: int = 0
    turns_in_flight_per_ip: int = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Caps":
        return cls(
            games_per_session=settings.session_games_open,
            games_per_ip=settings.ip_games_open,
            turns_per_session=settings.session_turns_in_flight,
            turns_in_flight_per_ip=settings.ip_turns_in_flight,
        )


NO_CAPS = Caps()


def _drop(counter: "Counter[str]", key: str) -> None:
    """Count one down, never keeping a zero entry (unbounded keys would be unbounded memory)."""
    if counter[key] <= 1:
        counter.pop(key, None)
    else:
        counter[key] -= 1


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
    owner: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gone: bool = False
    busy: bool = False  # a turn is running or waiting for the lock: the next one is refused
    turns: "deque[TurnRecord]" = field(default_factory=_transcript)
    preset: str | None = None  # None for a loaded game
    ip: str = ""  # the network that opened it, for the per-IP open-game cap


@dataclass
class _Reader:
    """Shared by a turn and its reader: set once the client has stopped reading."""

    gone: bool = False
    left: asyncio.Event = field(default_factory=asyncio.Event)  # `gone`, for a turn to wait on


async def _drain(
    queue: "asyncio.Queue[TurnEvent | None]", reader: _Reader
) -> AsyncGenerator[TurnEvent]:
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        reader.gone = True  # a turn still waiting for the lock now has nobody to serve
        reader.left.set()  # nor one waiting at the gate


ListSaves = Callable[[Callable[[str], bool]], list[SaveSummary]]


class AgentService:
    def __init__(
        self,
        deps: Deps,
        *,
        grace_s: float = 5.0,
        list_saves: ListSaves | None = None,
        owners: SaveOwners | None = None,
        quotas: Quotas | None = None,
        gate: TurnGate | None = None,
        caps: Caps = NO_CAPS,
    ) -> None:
        self._deps = deps
        self._grace_s = grace_s
        self._list_saves = list_saves  # blocking file reads: called in a worker thread
        self._owners = owners
        self._quotas = quotas
        self._gate = gate
        self._caps = caps
        self._slots: dict[str, _Slot] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        # turns running, and games being created; keys at zero are dropped (see `_drop`)
        self._flying_by_owner: Counter[str] = Counter()
        self._flying_by_ip: Counter[str] = Counter()
        self._reserved_by_owner: Counter[str] = Counter()
        self._reserved_by_ip: Counter[str] = Counter()

    def _slot(self, game: str, owner: str) -> _Slot:
        """The game's slot for its owner. A missing game and someone else's game fail alike, so a
        game id tells a stranger nothing."""
        slot = self._slots.get(game)
        if slot is None or not hmac.compare_digest(slot.owner.encode(), owner.encode()):
            raise ToolFailure("unknown_game", UNKNOWN_GAME)
        return slot

    def _register(self, view: NewGameView, preset: str | None, owner: str, ip: str) -> NewGameView:
        self._slots[view.game] = _Slot(TurnContext(game=view.game), owner, preset=preset, ip=ip)
        return view

    def _admit_game(self, owner: str, ip: str) -> Callable[[], None]:
        """Check the open-game quotas and reserve a place; the returned function releases it.
        Synchronous, so concurrent requests cannot all pass the check before one registers."""
        slots = self._slots.values()
        mine = sum(1 for s in slots if s.owner == owner) + self._reserved_by_owner[owner]
        if 0 < self._caps.games_per_session <= mine:
            raise ApiError(429, "quota", "you have too many games open; finish or delete one")
        if ip:
            theirs = sum(1 for s in slots if s.ip == ip) + self._reserved_by_ip[ip]
            if 0 < self._caps.games_per_ip <= theirs:
                raise ApiError(429, "quota", "too many games are open from your network")
        if self._quotas is not None:
            self._quotas.game_created(owner)
        self._reserved_by_owner[owner] += 1
        if ip:
            self._reserved_by_ip[ip] += 1

        def release() -> None:
            _drop(self._reserved_by_owner, owner)
            if ip:
                _drop(self._reserved_by_ip, ip)

        return release

    async def new_game(
        self, seed: int, preset: str = "standard", *, owner: str, ip: str = ""
    ) -> NewGameView:
        release = self._admit_game(owner, ip)
        try:
            view = await self._deps.client.new_game(seed, preset)
            return self._register(view, preset, owner, ip)
        finally:
            release()

    async def load_game(self, name: str, *, owner: str, ip: str = "") -> NewGameView:
        if self._owners is not None and not await asyncio.to_thread(self._owners.owns, name, owner):
            raise ToolFailure("bad_save", BAD_SAVE_MESSAGE)
        release = self._admit_game(owner, ip)
        try:
            view = await self._deps.client.load_game(name)
            return self._register(view, None, owner, ip)
        finally:
            release()

    @staticmethod
    def _outcome(slot: _Slot, brief: PlayerCaseView) -> Outcome:
        if brief.status == "playing":
            return "playing"
        if slot.ctx.outcome is not None:  # the engine cannot tell a give-up from a loss
            return slot.ctx.outcome
        return "won" if brief.status == "won" else "lost"

    async def state(self, game: str, *, owner: str) -> GameState:
        slot = self._slot(game, owner)
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

    async def games(self, *, owner: str) -> list[GameSummary]:
        """The open games, oldest first."""
        mine = [
            (game, slot)
            for game, slot in self._slots.items()
            if hmac.compare_digest(slot.owner.encode(), owner.encode())
        ]
        found = []
        for game, slot in mine:
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

    async def saves(self, *, owner: str) -> list[SaveSummary]:
        if self._list_saves is None or self._owners is None:
            return []
        owners = self._owners
        return await asyncio.to_thread(self._list_saves, lambda name: owners.owns(name, owner))

    def turns(self, game: str, *, owner: str) -> list[TurnRecord]:
        """The game's transcript, oldest first; a running turn is the last, not yet complete."""
        return list(self._slot(game, owner).turns)

    def start_turn(
        self,
        game: str,
        text: str,
        *,
        owner: str,
        ip: str = "",
        pending_id: str | None = None,
    ) -> AsyncGenerator[TurnEvent]:
        """Raises at once (before any streaming) for an unknown game, a turn in progress, a
        quota or rate refusal, or a full gate."""
        slot = self._slot(game, owner)  # first: a stranger learns nothing and uses up nothing
        self._ensure_free(slot)
        ticket = self._admit_turn(owner, ip)
        return self._start(
            slot,
            lambda: take_turn(self._deps, slot.ctx, text, pending_id=pending_id),
            kind="turn",
            text=text,
            owner=owner,
            ip=ip,
            ticket=ticket,
        )

    def start_confirm(
        self,
        game: str,
        pending_id: str,
        answer: Literal["yes", "no"],
        *,
        owner: str,
        ip: str = "",
    ) -> AsyncGenerator[TurnEvent]:
        """The confirm button. Raises at once for an unknown game, a turn in progress, a
        confirmation that is not the one waiting (409 `no_such_pending`), or a limit."""
        slot = self._slot(game, owner)
        self._ensure_free(slot)
        pending = slot.ctx.pending
        if pending is None or pending.id != pending_id:  # before the limits: costs no quota
            raise ApiError(409, "no_such_pending", "that confirmation is not waiting any more")
        ticket = self._admit_turn(owner, ip)
        return self._start(
            slot,
            lambda: take_confirm(self._deps, slot.ctx, pending_id, answer),
            kind="confirm",
            text=answer,
            owner=owner,
            ip=ip,
            ticket=ticket,
        )

    def _admit_turn(self, owner: str, ip: str) -> Ticket:
        """Check the in-flight caps and the turn rates, then take a place at the gate."""
        if 0 < self._caps.turns_per_session <= self._flying_by_owner[owner]:
            raise ApiError(409, "turn_in_progress", "you already have a turn running; wait for it")
        if ip and 0 < self._caps.turns_in_flight_per_ip <= self._flying_by_ip[ip]:
            message = "too many turns are running from your network"
            raise ApiError(429, "busy", message, retry_after=5)
        if self._quotas is not None:
            self._quotas.turn(owner, ip)
        if self._gate is None:
            return Ticket(None)
        try:
            return self._gate.admit()
        except Busy:
            raise ApiError(429, "busy", BUSY_TEXT, retry_after=5) from None

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
        owner: str,
        ip: str,
        ticket: Ticket,
    ) -> AsyncGenerator[TurnEvent]:
        # the callers ran `_ensure_free` with no await since, so the game is still free; from
        # here nothing raises before the done callbacks that give back the ticket are in place
        slot.busy = True
        self._flying_by_owner[owner] += 1
        if ip:
            self._flying_by_ip[ip] += 1
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
        task = asyncio.create_task(self._run(slot, events, queue, reader, record, ticket))
        self._tasks.add(task)  # a strong reference: the loop only keeps a weak one
        task.add_done_callback(self._finished)
        # Done callbacks run in order and however the task ended, even when it was cancelled
        # before its first step (a finally block would never be entered): free the game first,
        # then end the reader's stream, so a client that saw the end can start the next turn.
        task.add_done_callback(lambda _task: setattr(slot, "busy", False))
        task.add_done_callback(lambda _task: self._landed(owner, ip, ticket))
        task.add_done_callback(lambda _task: queue.put_nowait(None))
        return _drain(queue, reader)

    async def _run(
        self,
        slot: _Slot,
        events: Callable[[], AsyncIterator[TurnEvent]],
        queue: "asyncio.Queue[TurnEvent | None]",
        reader: _Reader,
        record: TurnRecord,
        ticket: Ticket,
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
                # wait() exactly once; the done callback closes the ticket however this ends
                outcome = await ticket.wait(
                    reader.left, lambda place: queue.put_nowait(Queued(position=place))
                )
                if outcome == "left":  # the client left while queued: give up the place
                    return
                if outcome == "timeout":  # never recorded: it did not run
                    queue.put_nowait(Clarify(reason="error", text=BUSY_TEXT))
                    queue.put_nowait(Done())
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

    def _landed(self, owner: str, ip: str, ticket: Ticket) -> None:
        """Give back what a turn held: its in-flight counts and its gate place."""
        _drop(self._flying_by_owner, owner)
        if ip:
            _drop(self._flying_by_ip, ip)
        ticket.close()

    def _finished(self, task: "asyncio.Task[None]") -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("a turn task died: %s", describe_failure(error))

    async def save_game(self, game: str, *, owner: str) -> SaveView:
        slot = self._slot(game, owner)
        async with slot.lock:  # wait for a running turn: the save is a clean state
            if slot.gone:
                raise ToolFailure("unknown_game", UNKNOWN_GAME)
            view = await self._deps.client.save_game(game)
            if self._owners is not None:
                await asyncio.to_thread(self._owners.claim, view.name, owner)
            return view

    async def delete_game(self, game: str, *, owner: str) -> None:
        slot = self._slot(game, owner)
        async with slot.lock:  # never orphan a running turn
            if slot.gone:
                raise ToolFailure("unknown_game", UNKNOWN_GAME)
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
