"""FastAPI app exposing the comparative decision stats."""

from datetime import datetime

from fastapi import FastAPI, Query

from gumshoe.stats import (
    DecisionView,
    SqliteStatsStore,
    StatsReport,
    build_report,
    recent_decisions,
)


def create_app(store: SqliteStatsStore) -> FastAPI:
    app = FastAPI(title="Gumshoe API")

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
