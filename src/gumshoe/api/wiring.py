"""Builds the real agent service from settings. The only api module that touches the MCP SDK."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from gumshoe.agent import AgentConfig
from gumshoe.api.service import AgentService
from gumshoe.config import Settings
from gumshoe.decider import DeciderConfigError
from gumshoe.stats import SqliteStatsStore


def agent_config(settings: Settings) -> AgentConfig:
    return AgentConfig(
        confidence_gate=settings.confidence_gate,
        confirm_gate=settings.confirm_gate,
        max_redrafts=settings.max_redrafts,
        dramatic_from=settings.dramatic_from,
        model_default=settings.persona_model_default,
        model_dramatic=settings.persona_model_dramatic,
    )


@asynccontextmanager
async def default_service(store: SqliteStatsStore) -> AsyncIterator[AgentService]:
    raise DeciderConfigError("jev", "the real service is wired in the next task")
    yield  # pragma: no cover
