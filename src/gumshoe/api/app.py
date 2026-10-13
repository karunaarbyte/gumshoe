"""FastAPI app: the comparative decision stats and the game."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import ApiError, error_body, status_for
from gumshoe.api.games import router as games_router
from gumshoe.api.service import AgentService
from gumshoe.api.wiring import default_service
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


def create_app(store: SqliteStatsStore, *, make_service: ServiceFactory | None = None) -> FastAPI:
    factory: ServiceFactory = make_service or default_service

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            try:
                app.state.service = await stack.enter_async_context(factory(store))
            except DeciderConfigError as exc:
                logger.warning("the game endpoints are off: %s", exc)
                app.state.service = None
            yield

    app = FastAPI(title="Gumshoe API", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(ToolFailure)
    async def tool_failure(request: Request, exc: ToolFailure) -> JSONResponse:
        if exc.code == "internal":
            logger.error("the game server failed: %s", exc.message)
        return JSONResponse(error_body(exc.code, exc.message), status_code=status_for(exc.code))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette logs the exception itself; the body never carries its text
        return JSONResponse(error_body("internal", "something went wrong"), status_code=500)

    app.include_router(games_router)

    # Plain `def` handlers run in FastAPI's thread pool, which suits blocking SQLite calls.
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
