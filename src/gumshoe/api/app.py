"""FastAPI app: the comparative decision stats and the game."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import ApiError, describe_validation, error_body, http_code, status_for
from gumshoe.api.games import MAX_TURN_CHARS, saves_router
from gumshoe.api.games import router as games_router
from gumshoe.api.info import MAX_ATTEMPTS, Health, Meta, PersonaModels, presets
from gumshoe.api.limits import BodyLimit
from gumshoe.api.service import AgentService
from gumshoe.api.wiring import default_service
from gumshoe.config import Settings, get_settings
from gumshoe.decider import DeciderConfigError
from gumshoe.stats import (
    DecisionView,
    SqliteStatsStore,
    StatsReport,
    build_report,
    recent_decisions,
)

logger = logging.getLogger(__name__)

ServiceFactory = Callable[[SqliteStatsStore], AbstractAsyncContextManager[AgentService]]


NOT_STARTED = "the server has not finished starting"


def cors_origins(settings: Settings) -> list[str]:
    """CORS_ORIGINS is a comma-separated list of exact origins; empty means no CORS at all."""
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


def create_app(
    store: SqliteStatsStore,
    *,
    make_service: ServiceFactory | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    factory: ServiceFactory = make_service or (lambda s: default_service(s, settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            try:
                app.state.service = await stack.enter_async_context(factory(store))
                app.state.game_off = None
            except DeciderConfigError as exc:
                logger.warning("the game endpoints are off: %s", exc)
                app.state.service = None
                app.state.game_off = f"the decider is not configured: {exc.message}"
            yield

    app = FastAPI(title="Gumshoe API", lifespan=lifespan)
    app.state.game_off = NOT_STARTED  # until the lifespan has run
    app.add_middleware(BodyLimit, max_bytes=settings.max_body_bytes)
    if origins := cors_origins(settings):  # added last, so it is outermost: 413s carry it too
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["content-type"],
        )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(ToolFailure)
    async def tool_failure(request: Request, exc: ToolFailure) -> JSONResponse:
        if exc.code == "internal":
            logger.error("the game server failed: %s", exc.message)
        return JSONResponse(error_body(exc.code, exc.message), status_code=status_for(exc.code))

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = error_body("bad_request", describe_validation(exc.errors()))
        return JSONResponse(body, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = error_body(http_code(exc.status_code), str(exc.detail))
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette logs the exception itself; the body never carries its text
        return JSONResponse(error_body("internal", "something went wrong"), status_code=500)

    app.include_router(games_router)
    app.include_router(saves_router)

    # Plain `def` handlers run in FastAPI's thread pool, which suits blocking SQLite calls.
    @app.get("/api/health")
    def health(request: Request) -> Health:
        off: str | None = getattr(request.app.state, "game_off", NOT_STARTED)
        return Health(
            game="off" if off else "on",
            reason=off,
            primary=settings.decider_primary,
            shadow=settings.decider_shadow,
            persona_models=PersonaModels(
                default=settings.persona_model_default, dramatic=settings.persona_model_dramatic
            ),
        )

    @app.get("/api/meta")
    def meta() -> Meta:
        return Meta(
            presets=presets(),
            default_preset="standard",
            max_attempts=MAX_ATTEMPTS,
            max_turn_chars=MAX_TURN_CHARS,
        )

    @app.get("/api/stats/decisions")
    def decision_stats(
        node: str | None = None, since: datetime | None = None, include_cold: bool = False
    ) -> StatsReport:
        calls = store.fetch_calls(node=node, since=since)
        return build_report(calls, include_cold=include_cold, since=since)

    @app.get("/api/decisions")
    def decisions(
        limit: int = Query(20, ge=1, le=200), node: str | None = None
    ) -> list[DecisionView]:
        return recent_decisions(store.fetch_recent(limit=limit, node=node))

    return app
