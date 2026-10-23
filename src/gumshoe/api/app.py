"""FastAPI app: the comparative decision stats and the game."""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from gumshoe.agent import ToolFailure
from gumshoe.api.admin import admin_token_of, require_admin
from gumshoe.api.errors import ApiError, describe_validation, error_body, http_code, status_for
from gumshoe.api.games import MAX_TURN_CHARS, Service, saves_router
from gumshoe.api.games import router as games_router
from gumshoe.api.info import (
    MAX_ATTEMPTS,
    AdminUsage,
    ClientUsage,
    Health,
    Meta,
    PersonaModels,
    presets,
)
from gumshoe.api.limits import BodyLimit
from gumshoe.api.probe import PersonaProbe
from gumshoe.api.ratelimit import Quotas
from gumshoe.api.ratemiddleware import RequestRate
from gumshoe.api.redact import for_player
from gumshoe.api.service import AgentService
from gumshoe.api.session import Owner, Sessions
from gumshoe.api.shield import OriginCheck
from gumshoe.api.wiring import default_service
from gumshoe.config import Settings, get_settings
from gumshoe.decider import DeciderConfigError, describe_failure
from gumshoe.stats import (
    DecisionView,
    Price,
    SqliteStatsStore,
    StatsReport,
    build_report,
    disagreeing,
    recent_decisions,
)

logger = logging.getLogger(__name__)

ServiceFactory = Callable[[SqliteStatsStore], AbstractAsyncContextManager[AgentService]]


NOT_STARTED = "the server has not finished starting"


MAX_IDS = 200

# The shape every decision id takes (`uuid4().hex`). Anything else is refused before any lookup.
DECISION_ID = re.compile(r"[0-9a-f]{32}")
NO_SUCH_DECISION = "no such decision"


def prices_of(settings: Settings) -> dict[str, Price]:
    return {
        "jev": Price(settings.jev_usd_per_mtok_in, settings.jev_usd_per_mtok_out),
        "nimble": Price(settings.nimble_usd_per_mtok_in, settings.nimble_usd_per_mtok_out),
    }


def create_app(
    store: SqliteStatsStore,
    *,
    make_service: ServiceFactory | None = None,
    settings: Settings | None = None,
    personas_up: Callable[[], Awaitable[bool]] | None = None,
    sessions: Sessions | None = None,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    sessions = sessions or Sessions.from_settings(settings)
    personas_up = (
        personas_up
        or PersonaProbe(
            settings.ollama_base_url,
            (settings.persona_model_default, settings.persona_model_dramatic),
        ).up
    )
    prices = prices_of(settings)
    # one table for the middleware and the service; `clock` is for tests (a fake one)
    quotas = Quotas(settings, clock=clock or time.monotonic)
    factory: ServiceFactory = make_service or (
        lambda s: default_service(s, settings, sessions, quotas)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            try:
                app.state.service = await stack.enter_async_context(factory(store))
                app.state.game_off = None
            except DeciderConfigError as exc:
                logger.warning("the game endpoints are off: %s", describe_failure(exc))
                app.state.service = None
                app.state.game_off = f"the decider is not configured: {exc.message}"
            yield

    # No slash redirects: a 307 from `/api/admin/usage/` would show the route exists.
    app = FastAPI(title="Gumshoe API", lifespan=lifespan, redirect_slashes=False)
    app.state.game_off = NOT_STARTED  # until the lifespan has run
    app.state.sessions = sessions
    app.state.quotas = quotas
    app.state.trust_proxy = settings.trust_proxy
    app.state.admin_token = admin_token_of(settings.admin_token.get_secret_value())
    app.add_middleware(BodyLimit, max_bytes=settings.max_body_bytes)
    allowed_origins = (
        *settings.cors_origin_list,
        *([settings.public_origin] if settings.public_origin else []),
    )
    app.add_middleware(OriginCheck, allowed=allowed_origins, local=not settings.public_mode)
    app.add_middleware(RequestRate, quotas=quotas, trust_proxy=settings.trust_proxy)
    if origins := settings.cors_origin_list:  # added last, so it is outermost: 413s carry it too
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["content-type", "authorization"],
        )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        body = error_body(exc.code, exc.message)
        return JSONResponse(body, status_code=exc.status, headers=headers)

    @app.exception_handler(ToolFailure)
    async def tool_failure(request: Request, exc: ToolFailure) -> JSONResponse:
        if exc.code == "internal":
            logger.error("the game server failed: %s", exc.message)
        return JSONResponse(error_body(exc.code, exc.message), status_code=status_for(exc.code))

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = error_body("bad_request", describe_validation(exc.errors()))
        return JSONResponse(body, status_code=422)

    def gated(request: Request) -> bool:
        """Whether the path is one of the admin routes (found from the routes themselves)."""
        return any(
            isinstance(route, APIRoute)
            and any(d.dependency is require_admin for d in route.dependencies)
            and route.matches(request.scope)[0] is not Match.NONE
            for route in app.router.routes
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405 and gated(request):
            # Routing answers a wrong method before the gate runs: run it here, so without the
            # token the answer is the plain 404 (counted and logged), not a 405 with `Allow`.
            try:
                require_admin(request)
            except ApiError as refused:
                return await api_error(request, refused)
        body = error_body(http_code(exc.status_code), str(exc.detail))
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette logs the exception itself; the body never carries its text
        return JSONResponse(error_body("internal", "something went wrong"), status_code=500)

    app.include_router(games_router)
    app.include_router(saves_router)

    # Plain `def` handlers run in FastAPI's thread pool, which suits blocking SQLite calls. Health
    # is `async` instead: its one outside call (the model probe) is awaited, never blocking.
    @app.get("/api/health")
    async def health(request: Request) -> Health:
        off: str | None = getattr(request.app.state, "game_off", NOT_STARTED)
        service = getattr(request.app.state, "service", None)
        return Health(
            game="off" if off else "on",
            reason=off,
            primary=settings.decider_primary,
            shadow=settings.decider_shadow,
            persona_models=PersonaModels(
                default=settings.persona_model_default, dramatic=settings.persona_model_dramatic
            ),
            personas="up" if await personas_up() else "down",
            mode=service.decider_mode() if service is not None else "normal",
        )

    @app.get("/api/meta")
    def meta() -> Meta:
        return Meta(
            presets=presets(),
            default_preset="standard",
            max_attempts=MAX_ATTEMPTS,
            max_turn_chars=MAX_TURN_CHARS,
        )

    @app.get("/api/stats/decisions", dependencies=[Depends(require_admin)])
    def decision_stats(
        node: str | None = None, since: datetime | None = None, include_cold: bool = False
    ) -> StatsReport:
        calls = store.fetch_calls(node=node, since=since)
        return build_report(
            calls,
            include_cold=include_cold,
            since=since,
            prices=prices,
            confirm_gate=settings.confirm_gate,
            dramatic_from=settings.dramatic_from,
        )

    @app.get("/api/decisions", dependencies=[Depends(require_admin)])
    def decisions(
        limit: int = Query(20, ge=1, le=200),
        node: str | None = None,
        ids: str | None = Query(None, max_length=MAX_IDS * 65),
        disagree: bool = False,
        since: datetime | None = None,
        question: str | None = Query(None, max_length=64),
    ) -> list[DecisionView]:
        """The latest decisions; or exactly the ones in `ids` (comma-separated: `limit` and
        `since` do not apply). `disagree=true` keeps only head-to-heads where the backends differ,
        on `question` alone when that is given. `since` keeps decisions started at or after it."""
        if question is not None and not disagree:
            raise ApiError(422, "bad_request", "question narrows disagree=true; set that too")
        if ids is not None:
            wanted = [i for i in ids.split(",") if i]
            if not 0 < len(wanted) <= MAX_IDS:
                raise ApiError(422, "bad_request", f"ids takes 1 to {MAX_IDS} decision ids")
            calls = [c for c in store.fetch_decisions(wanted) if node is None or c.node == node]
        elif disagree:
            calls = store.fetch_calls(node=node, since=since)  # all of them: the filter needs them
        else:
            calls = store.fetch_recent(limit=limit, node=node, since=since)
        if disagree:
            calls = disagreeing(calls, settings.confirm_gate, settings.dramatic_from, question)
        views = recent_decisions(
            calls,
            prices=prices,
            confirm_gate=settings.confirm_gate,
            dramatic_from=settings.dramatic_from,
        )
        return views if ids is not None else views[:limit]

    @app.get("/api/decisions/{decision_id}", dependencies=[Depends(require_admin)])
    def decision(decision_id: str = Path(max_length=64)) -> DecisionView:
        """One decision. Until its first row is written (a primary's record lands a moment
        after the turn's event), 404 `not_recorded_yet`: the UI retries."""
        views = recent_decisions(
            store.fetch_decisions([decision_id]),
            prices=prices,
            confirm_gate=settings.confirm_gate,
            dramatic_from=settings.dramatic_from,
        )
        if not views:
            raise ApiError(404, "not_recorded_yet", "that decision has not been recorded yet")
        return views[0]

    @app.get("/api/games/{game}/decisions/{decision_id}")
    async def player_decision(
        game: str, decision_id: str, service: Service, owner: Owner
    ) -> DecisionView:
        """A decision from the caller's own game, without the player's typed text. The owner check
        comes first (a stranger gets the missing game's answer); then an id that is malformed or
        not in this game's transcript gets one plain 404, whether or not it exists elsewhere."""
        mentioned = service.decision_ids(game, owner=owner)  # on the loop: in-memory state
        if DECISION_ID.fullmatch(decision_id) is None or decision_id not in mentioned:
            raise ApiError(404, "not_found", NO_SUCH_DECISION)
        calls = await asyncio.to_thread(store.fetch_decisions, [decision_id])  # blocking SQLite
        views = recent_decisions(
            calls,
            prices=prices,
            confirm_gate=settings.confirm_gate,
            dramatic_from=settings.dramatic_from,
        )
        if not views:
            raise ApiError(404, "not_recorded_yet", "that decision has not been recorded yet")
        return for_player(views[0])

    @app.get("/api/admin/usage", dependencies=[Depends(require_admin)])
    def admin_usage(request: Request) -> AdminUsage:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        totals = store.usage_totals(today)
        service: AgentService | None = getattr(request.app.state, "service", None)
        snap = service.usage_snapshot() if service is not None else {}
        top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return AdminUsage(
            day=today,
            jev_tokens_today=sum(totals.values()),
            jev_daily_cap=settings.jev_daily_tokens,
            jev_ip_daily_cap=settings.jev_ip_daily_tokens,
            mode=service.decider_mode() if service is not None else "normal",
            games_open=snap.get("games_open", 0),
            turns_running=snap.get("turns_running", 0),
            queued=snap.get("queued", 0),
            shadow_skipped=snap.get("shadow_skipped", 0),
            sessions_seen=request.app.state.sessions.issued,
            saves_held=snap.get("saves_held", 0),
            top_clients=[ClientUsage(key=k, tokens=t) for k, t in top],
        )

    return app
