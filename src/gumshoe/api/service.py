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
import contextlib
import hmac
import logging
import time
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
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
from gumshoe.api.redact import PlayerBrief
from gumshoe.api.saveowners import SaveOwners
from gumshoe.cases import DEFAULT_PACK, NotebookView, PlayerCaseView, RevealView, pack_info
from gumshoe.config import Settings
from gumshoe.decider import client_key, describe_failure

logger = logging.getLogger(__name__)

SHUTTING_DOWN = "The game server is shutting down. Please try again in a moment."
BUSY_TEXT = "The detectives are busy right now. Please try again in a moment."
MAX_TURNS_KEPT = 200  # per game, for the transcript; the oldest are dropped first
COLD_TEXT = "That case went cold. Start a new game."
TOMBSTONE_TTL_S = 24 * 3600.0
TOMBSTONE_CAP = 5000


Outcome = Literal["playing", "won", "lost", "gave_up"]


@dataclass(frozen=True)
class Caps:
    """How much one session or one IP may hold at once. 0 = unlimited."""

    games_per_session: int = 0
    games_per_ip: int = 0
    turns_per_session: int = 0
    turns_in_flight_per_ip: int = 0
    saves_per_session: int = 0
    saves_per_ip: int = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Caps":
        return cls(
            games_per_session=settings.session_games_open,
            games_per_ip=settings.ip_games_open,
            turns_per_session=settings.session_turns_in_flight,
            turns_in_flight_per_ip=settings.ip_turns_in_flight,
            saves_per_session=settings.session_saves,
            saves_per_ip=settings.ip_saves,
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
    the answer. The pack and preset come from the game itself, also after a load."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief: PlayerBrief  # locked names blanked
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
    preset: str | None = None
    pack: str = DEFAULT_PACK
    ip: str = ""  # the network that opened it, for the per-IP open-game cap
    last_active: float = 0.0  # clock time of registration or of the last turn's end


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


class _Tombstones:
    """Games that expired, by (owner, game): the owner is told, nobody else can tell."""

    def __init__(
        self,
        cap: int = TOMBSTONE_CAP,
        ttl_s: float = TOMBSTONE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cap = cap
        self._ttl = ttl_s
        self._clock = clock
        self._until: OrderedDict[tuple[str, str], float] = OrderedDict()

    def add(self, owner: str, game: str) -> None:
        now = self._clock()
        # One ttl for all and every add goes to the end: the map is in deadline order, so the
        # expired ones are at the head (amortised O(1) per add).
        while self._until:
            head, until = next(iter(self._until.items()))
            if now < until:
                break
            del self._until[head]
        self._until[(owner, game)] = now + self._ttl
        self._until.move_to_end((owner, game))
        while len(self._until) > self._cap:
            self._until.popitem(last=False)

    def has(self, owner: str, game: str) -> bool:
        until = self._until.get((owner, game))
        if until is None:
            return False
        if self._clock() >= until:
            del self._until[(owner, game)]
            return False
        return True


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
        clock: Callable[[], float] = time.monotonic,
        idle_s: float = 0.0,
    ) -> None:
        self._deps = deps
        self._grace_s = grace_s
        self._list_saves = list_saves  # blocking file reads: called in a worker thread
        self._owners = owners
        self._quotas = quotas
        self._gate = gate
        self._caps = caps
        self._clock = clock
        self._idle_s = idle_s  # 0 = games never expire
        self._tombstones = _Tombstones(clock=clock)
        self._save_lock = asyncio.Lock()  # check-and-save, one at a time: the caps stay exact
        self._slots: dict[str, _Slot] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        # turns running, and games being created; keys at zero are dropped (see `_drop`)
        self._flying_by_owner: Counter[str] = Counter()
        self._flying_by_ip: Counter[str] = Counter()
        self._reserved_by_owner: Counter[str] = Counter()
        self._reserved_by_ip: Counter[str] = Counter()

    def _slot(self, game: str, owner: str) -> _Slot:
        """The game's slot for its owner. A missing game and someone else's game fail alike, so a
        game id tells a stranger nothing; only the owner of an expired game is told it went cold."""
        slot = self._slots.get(game)
        if slot is None:
            if self._tombstones.has(owner, game):
                raise ApiError(410, "cold", COLD_TEXT)
            raise ToolFailure("unknown_game", UNKNOWN_GAME)
        if not hmac.compare_digest(slot.owner.encode(), owner.encode()):
            raise ToolFailure("unknown_game", UNKNOWN_GAME)
        return slot

    def _register(self, view: NewGameView, owner: str, ip: str) -> NewGameView:
        slot = _Slot(TurnContext(game=view.game), owner, preset=view.preset, pack=view.pack, ip=ip)
        slot.last_active = self._clock()
        self._slots[view.game] = slot
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
        self,
        seed: int,
        preset: str = "standard",
        pack: str = DEFAULT_PACK,
        *,
        owner: str,
        ip: str = "",
    ) -> NewGameView:
        # checked before admission, so a refused request charges no quota; the message never
        # echoes the pack id, which the client chose
        info = pack_info(pack)
        if info is None:
            raise ToolFailure("bad_argument", "unknown setting")
        if preset not in info.presets:
            raise ToolFailure(
                "bad_argument", f"this setting hosts these presets: {', '.join(info.presets)}"
            )
        release = self._admit_game(owner, ip)
        try:
            view = await self._deps.client.new_game(seed, preset, pack)
            return self._register(view, owner, ip)
        finally:
            release()

    async def load_game(self, name: str, *, owner: str, ip: str = "") -> NewGameView:
        if self._owners is not None and not await asyncio.to_thread(self._owners.owns, name, owner):
            raise ToolFailure("bad_save", BAD_SAVE_MESSAGE)
        release = self._admit_game(owner, ip)
        try:
            view = await self._deps.client.load_game(name)
            return self._register(view, owner, ip)
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

    def decision_ids(self, game: str, *, owner: str) -> set[str]:
        """Every decision id the game's turns mention, for deciding who may read which decision."""
        found: set[str] = set()
        for record in self._slot(game, owner).turns:
            for event in record.events:
                decision_id = getattr(event, "decision_id", None)
                if decision_id:
                    found.add(decision_id)
        return found

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
        task = asyncio.create_task(self._run(slot, events, queue, reader, record, ticket, ip))
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
        ip: str,
    ) -> None:
        def emit(event: TurnEvent) -> None:
            record.events.append(event)
            queue.put_nowait(event)

        # the turn's decisions are counted against this network's share of the Jev budget; set
        # here, inside the turn's own task, so it never reaches the caller's context
        token = client_key.set(ip)
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
            slot.last_active = self._clock()  # idleness is measured from a turn's end
            client_key.reset(token)

    def usage_snapshot(self) -> dict[str, int]:
        """The load figures for the admin usage report. Event-loop state: call it on the loop."""
        gate = self._gate
        return {
            "games_open": len(self._slots),
            "turns_running": sum(1 for s in self._slots.values() if s.busy),
            "queued": gate.queued if gate is not None else 0,
            "shadow_skipped": int(getattr(self._deps.decider, "shadow_skipped", 0)),
        }

    def saves_held(self) -> int:
        """The saves on disk. Reads the folder: call it off the loop (in a thread)."""
        return self._owners.count_all() if self._owners is not None else 0

    def decider_mode(self) -> Literal["normal", "slow"]:
        """Slow mode is the global Jev budget spent (the decider's `mode`); a decider with no
        budget is always normal."""
        mode = getattr(self._deps.decider, "mode", "normal")
        return "slow" if mode == "slow" else "normal"

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

    async def save_game(self, game: str, *, owner: str, ip: str = "") -> SaveView:
        """Save the game for its owner. Over a save cap: 429 `quota`, before anything is written.

        The save is written first and claimed after (a sidecar with no save is an orphan that
        purge removes). A save that cannot be claimed is removed again, so no unowned save
        counts toward the host's saves."""
        slot = self._slot(game, owner)
        async with slot.lock:  # wait for a running turn: the save is a clean state
            if slot.gone:
                raise ToolFailure("unknown_game", UNKNOWN_GAME)
            owners = self._owners
            if owners is None:
                return await self._deps.client.save_game(game)
            async with self._save_lock:  # saves are rare and quick: one at a time
                await self._check_save_caps(owners, owner, ip)
                view = await self._deps.client.save_game(game)
                try:
                    await asyncio.to_thread(owners.claim, view.name, owner, ip)
                except OSError as exc:
                    logger.error("a save could not be claimed: %s", type(exc).__name__)
                    with contextlib.suppress(OSError):
                        await asyncio.to_thread(owners.delete, view.name)
                    raise ApiError(500, "internal", "the game could not be saved") from None
                except BaseException:
                    # Cancelled (or worse) between the write and the claim: an unclaimed save
                    # belongs to nobody yet still counts toward the host's saves. Deleted
                    # inline, since a second await could be cancelled too; a claim thread still
                    # finishing leaves at most an orphan sidecar, which purge removes.
                    with contextlib.suppress(OSError):
                        owners.delete(view.name)
                    raise
                return view

    async def _check_save_caps(self, owners: SaveOwners, owner: str, ip: str) -> None:
        """Refuse a save over a cap. The answer names no save and no count: it tells the caller
        nothing about saves that are not theirs."""
        caps = self._caps
        if 0 < caps.saves_per_session <= await asyncio.to_thread(owners.count_owned, owner):
            raise ApiError(429, "quota", "you have too many saves; delete one first")
        if ip and 0 < caps.saves_per_ip <= await asyncio.to_thread(owners.count_ip, ip):
            raise ApiError(429, "quota", "too many saves from your network")

    async def delete_save(self, name: str, *, owner: str) -> None:
        """Delete the caller's save. Someone else's save fails exactly as a missing one does."""
        owners = self._owners
        if owners is None or not await asyncio.to_thread(owners.owns, name, owner):
            raise ToolFailure("bad_save", BAD_SAVE_MESSAGE)
        await asyncio.to_thread(owners.delete, name)

    async def purge_saves(self, retention_s: float) -> int:
        """Delete saves older than `retention_s`, and orphaned sidecars. 0 = keep everything."""
        owners = self._owners
        if owners is None or retention_s <= 0:
            return 0
        async with self._save_lock:  # a save written but not yet claimed is not an orphan
            return await asyncio.to_thread(owners.purge, retention_s)

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

    async def expire_idle(self) -> int:
        """Close the games idle for `idle_s` or more. A game with a turn running or waiting is
        skipped; the others are closed under their lock, after re-checking that nothing touched
        them while expiry waited for it."""
        if self._idle_s <= 0:
            return 0
        closed = 0
        for game, slot in list(self._slots.items()):
            if slot.busy or self._clock() - slot.last_active < self._idle_s:
                continue
            async with slot.lock:
                if (
                    slot.gone
                    or slot.busy
                    or self._clock() - slot.last_active < self._idle_s
                    or self._slots.get(game) is not slot
                ):
                    continue
                try:
                    await self._deps.client.close_game(game)
                except ToolFailure as exc:
                    if exc.code != "unknown_game":
                        logger.warning("could not close an idle game: %s", exc.code)
                        continue
                slot.gone = True
                self._slots.pop(game, None)
                self._tombstones.add(slot.owner, game)
                closed += 1
        return closed

    async def maintain(
        self,
        *,
        interval_s: float = 60.0,
        purge_every_s: float = 3600.0,
        retention_s: float = 0.0,
        housekeeping: Callable[[], object] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Housekeeping, forever: purge old saves once at startup, then close idle games every
        `interval_s` and purge old saves (and run `housekeeping`, off the event loop) every
        `purge_every_s`. A failing step is logged (class
        name only) and the loop goes on."""
        last_purge = self._clock()
        try:
            await self.purge_saves(retention_s)  # once at startup, then on the schedule below
        except Exception as exc:
            logger.error("purging old saves failed: %s", type(exc).__name__)
        while True:
            await sleep(interval_s)
            try:
                await self.expire_idle()
            except Exception as exc:
                logger.error("expiring idle games failed: %s", type(exc).__name__)
            if self._clock() - last_purge >= purge_every_s:
                last_purge = self._clock()
                try:
                    await self.purge_saves(retention_s)
                except Exception as exc:
                    logger.error("purging old saves failed: %s", type(exc).__name__)
                if housekeeping is not None:
                    try:
                        await asyncio.to_thread(housekeeping)
                    except Exception as exc:
                        logger.error("housekeeping failed: %s", type(exc).__name__)

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self._grace_s)
