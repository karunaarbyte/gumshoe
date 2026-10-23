"""The game endpoints: create, load, read, play (as server-sent events), save and delete."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from gumshoe.agent import EVENT_ADAPTER, SaveView, ToolFailure, TurnEvent
from gumshoe.api.errors import ApiError
from gumshoe.api.service import AgentService, GameState, GameSummary, SaveSummary, TurnRecord
from gumshoe.api.session import NewOwner, Owner, optional_owner
from gumshoe.cases import PlayerCaseView

router = APIRouter(prefix="/api/games")
saves_router = APIRouter(prefix="/api/saves")

MAX_TURN_CHARS = 1000
PING_INTERVAL_S = 15.0  # a comment line this often while a turn is quiet, so proxies keep it open
PING = b": ping\n\n"


class NewGameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: StrictInt
    preset: str = Field("standard", max_length=32)


class LoadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


class GameCreated(BaseModel):
    """A new or loaded game. No seed (see GameState); the preset only for a new game."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    game: str
    brief: PlayerCaseView
    preset: str | None


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)
    # the id of the confirmation on screen, if any (from the `confirm` event): only a yes that
    # carries it can run the pending action
    pending_id: str | None = Field(None, min_length=1, max_length=64)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_id: str = Field(min_length=1, max_length=64)
    answer: Literal["yes", "no"]


def service_of(request: Request) -> AgentService:
    service: AgentService | None = getattr(request.app.state, "service", None)
    if service is None:
        raise ApiError(503, "unavailable", "the game is not available right now")
    return service


Service = Annotated[AgentService, Depends(service_of)]


def sse(event: TurnEvent) -> bytes:
    """One event as an SSE block. The JSON is one line, so the block is always two lines."""
    return f"event: {event.kind}\ndata: {EVENT_ADAPTER.dump_json(event).decode()}\n\n".encode()


@router.post("")
async def create(body: NewGameBody, service: Service, owner: NewOwner) -> GameCreated:
    view = await service.new_game(body.seed, body.preset, owner=owner)
    return GameCreated(game=view.game, brief=view.brief, preset=body.preset)


@router.get("")
async def open_games(
    service: Service, owner: Annotated[str | None, Depends(optional_owner)]
) -> list[GameSummary]:
    if not owner:  # a visitor with no session has no games, which is not an error
        return []
    return await service.games(owner=owner)


@router.post("/load")
async def load(body: LoadBody, service: Service, owner: NewOwner) -> GameCreated:
    view = await service.load_game(body.name, owner=owner)
    return GameCreated(game=view.game, brief=view.brief, preset=None)


@router.get("/{game}")
async def read(game: str, service: Service, owner: Owner) -> GameState:
    return await service.state(game, owner=owner)


async def _pinged(events: AsyncIterator[TurnEvent], interval_s: float) -> AsyncGenerator[bytes]:
    """Each event as SSE, plus a `: ping` comment whenever `interval_s` passes without one.

    The next event is awaited in a task that a quiet spell never cancels (cancelling the read
    would close the event stream). When the client leaves, that task is cancelled, which closes
    the stream and so tells the service the reader is gone."""
    following = asyncio.ensure_future(anext(events))
    try:
        while True:
            done, _ = await asyncio.wait({following}, timeout=interval_s)
            if not done:
                yield PING
                continue
            try:
                event = following.result()
            except StopAsyncIteration:
                return
            yield sse(event)
            following = asyncio.ensure_future(anext(events))
    finally:
        following.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await following
        await _close(events)  # the read is over, so the stream can be closed now


async def _close(events: AsyncIterator[TurnEvent]) -> None:
    """Close the event stream so the service learns its reader is gone, without waiting for GC."""
    if (aclose := getattr(events, "aclose", None)) is not None:
        await aclose()


class _Pinged:
    """`_pinged`, but closing it always closes `events`, even when it was never read from (a
    generator closed before its first step never runs its `finally`)."""

    def __init__(self, events: AsyncIterator[TurnEvent], interval_s: float) -> None:
        self._events = events
        self._stream = _pinged(events, interval_s)

    def __aiter__(self) -> "_Pinged":
        return self

    def __anext__(self) -> Awaitable[bytes]:
        return self._stream.__anext__()

    async def aclose(self) -> None:
        await self._stream.aclose()
        await _close(self._events)


def with_pings(events: AsyncIterator[TurnEvent], interval_s: float) -> _Pinged:
    return _Pinged(events, interval_s)


def event_stream(events: AsyncIterator[TurnEvent]) -> StreamingResponse:
    # PING_INTERVAL_S is read here, at call time, so a test can shorten it
    return StreamingResponse(
        with_pings(events, PING_INTERVAL_S),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{game}/turn")
async def play(game: str, body: TurnBody, service: Service, owner: Owner) -> StreamingResponse:
    # an unknown game (404) or a turn in progress (409) raises here, before streaming starts
    return event_stream(
        service.start_turn(game, body.text, owner=owner, pending_id=body.pending_id)
    )


@router.post("/{game}/confirm")
async def confirm(
    game: str, body: ConfirmBody, service: Service, owner: Owner
) -> StreamingResponse:
    """The confirm and cancel buttons: no decision, the same events as a turn."""
    return event_stream(service.start_confirm(game, body.pending_id, body.answer, owner=owner))


@router.get("/{game}/turns")
async def transcript(game: str, service: Service, owner: Owner) -> list[TurnRecord]:
    return service.turns(game, owner=owner)


@router.post("/{game}/save")
async def save(game: str, service: Service, owner: Owner) -> SaveView:
    try:
        return await service.save_game(game, owner=owner)
    except ToolFailure as exc:
        if exc.code == "bad_save":  # the write failed: the server's fault, not the request's
            raise ApiError(500, exc.code, exc.message) from exc
        raise


@router.delete("/{game}", status_code=204)
async def delete(game: str, service: Service, owner: Owner) -> Response:
    await service.delete_game(game, owner=owner)
    return Response(status_code=204)


@saves_router.get("")
async def saves(
    service: Service, owner: Annotated[str | None, Depends(optional_owner)]
) -> list[SaveSummary]:
    """The caller's saves, newest first: name, when, pack and how the game stood. Never a case."""
    if owner is None:
        return []
    return await service.saves(owner=owner)
