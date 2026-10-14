"""The game endpoints: create, load, read, play (as server-sent events), save and delete."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from gumshoe.agent import EVENT_ADAPTER, NewGameView, SaveView, ToolFailure, TurnEvent
from gumshoe.api.errors import ApiError
from gumshoe.api.service import AgentService, GameState

router = APIRouter(prefix="/api/games")

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


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)
    # the id of the confirmation on screen, if any (from the `confirm` event): only a yes that
    # carries it can run the pending action
    pending_id: str | None = Field(None, min_length=1, max_length=64)


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
async def create(body: NewGameBody, service: Service) -> NewGameView:
    return await service.new_game(body.seed, body.preset)


@router.post("/load")
async def load(body: LoadBody, service: Service) -> NewGameView:
    return await service.load_game(body.name)


@router.get("/{game}")
async def read(game: str, service: Service) -> GameState:
    return await service.state(game)


async def with_pings(events: AsyncIterator[TurnEvent], interval_s: float) -> AsyncGenerator[bytes]:
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


def event_stream(events: AsyncIterator[TurnEvent]) -> StreamingResponse:
    # PING_INTERVAL_S is read here, at call time, so a test can shorten it
    return StreamingResponse(
        with_pings(events, PING_INTERVAL_S),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{game}/turn")
async def play(game: str, body: TurnBody, service: Service) -> StreamingResponse:
    # an unknown game (404) or a turn in progress (409) raises here, before streaming starts
    return event_stream(service.start_turn(game, body.text, pending_id=body.pending_id))


@router.post("/{game}/save")
async def save(game: str, service: Service) -> SaveView:
    try:
        return await service.save_game(game)
    except ToolFailure as exc:
        if exc.code == "bad_save":  # the write failed: the server's fault, not the request's
            raise ApiError(500, exc.code, exc.message) from exc
        raise


@router.delete("/{game}", status_code=204)
async def delete(game: str, service: Service) -> Response:
    await service.delete_game(game)
    return Response(status_code=204)
