"""Builds the real agent service from settings. The only api module that touches the MCP SDK."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from mcp.client import Client

from gumshoe.agent import AgentConfig, Deps, GameClient, OllamaLlm
from gumshoe.api.service import AgentService
from gumshoe.config import Settings, get_settings
from gumshoe.decider import make_decider
from gumshoe.mcp_server import GameHost
from gumshoe.mcp_server.tools import build_server
from gumshoe.stats import SqliteStatsStore


def agent_config(settings: Settings) -> AgentConfig:
    return AgentConfig(
        confidence_gate=settings.confidence_gate,
        confirm_gate=settings.confirm_gate,
        max_redrafts=settings.max_redrafts,
        dramatic_from=settings.dramatic_from,
        model_default=settings.persona_model_default,
        model_dramatic=settings.persona_model_dramatic,
        turn_timeout_s=settings.turn_timeout_s,
    )


@asynccontextmanager
async def default_service(
    store: SqliteStatsStore, settings: Settings | None = None
) -> AsyncIterator[AgentService]:
    """The service the app runs on. The injected store doubles as the decision recorder (never a
    second store on the same file). A missing Jev key raises `DeciderConfigError` before
    anything is opened. On exit: turns are cancelled, then the MCP client closes, then the
    decider (so background records drain), then the Ollama client."""
    settings = settings or get_settings()
    decider = make_decider(settings, recorder=store)
    llm = OllamaLlm(settings.ollama_base_url, timeout=settings.llm_timeout_s)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(llm.aclose)
        stack.push_async_callback(decider.aclose)
        raw = await stack.enter_async_context(Client(build_server(GameHost())))
        service = AgentService(Deps(GameClient(raw), decider, llm, agent_config(settings)))
        stack.push_async_callback(service.aclose)
        yield service
