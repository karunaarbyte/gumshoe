"""Builds the real agent service from settings. The only api module that touches the MCP SDK."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from mcp.client import Client

from gumshoe.agent import AgentConfig, Deps, GameClient, OllamaLlm
from gumshoe.api.saveowners import SaveOwners
from gumshoe.api.service import AgentService, SaveSummary
from gumshoe.api.session import Sessions
from gumshoe.config import Settings, get_settings
from gumshoe.decider import make_decider
from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.saves import NAME, read_save
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


MAX_SAVES_LISTED = 200


def save_index(folder: Path, owns: Callable[[str], bool]) -> list[SaveSummary]:
    """The readable saves in `folder`, newest first. Reads only the pack and the game's status
    out of each file: a save holds the whole case, and none of it is passed on. A file that
    cannot be read is left out (the load would refuse it anyway). Only saves `owns` accepts are
    listed."""
    if not folder.is_dir():
        return []
    found: list[SaveSummary] = []
    for path in folder.glob("*.json"):
        if NAME.fullmatch(path.stem) is None:
            continue  # not a name the host makes
        if not owns(path.stem):
            continue
        try:
            save = read_save(folder, path.stem)
            made = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            found.append(
                SaveSummary(
                    name=path.stem,
                    created_at=made.isoformat(timespec="seconds"),
                    pack=save.pack,
                    status=json.loads(save.state)["status"],
                )
            )
        except (GameError, OSError, ValueError, KeyError, TypeError, RecursionError):
            continue
    found.sort(key=lambda s: (s.created_at, s.name), reverse=True)
    return found[:MAX_SAVES_LISTED]


@asynccontextmanager
async def default_service(
    store: SqliteStatsStore,
    settings: Settings | None = None,
    sessions: Sessions | None = None,
) -> AsyncIterator[AgentService]:
    """The service the app runs on. The injected store doubles as the decision recorder (never a
    second store on the same file). A missing Jev key raises `DeciderConfigError` before
    anything is opened. On exit: turns are cancelled, then the MCP client closes, then the
    decider (so background records drain), then the Ollama client."""
    settings = settings or get_settings()
    sessions = sessions or Sessions.from_settings(settings)
    decider = make_decider(settings, recorder=store)
    llm = OllamaLlm(settings.ollama_base_url, timeout=settings.llm_timeout_s)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(llm.aclose)
        stack.push_async_callback(decider.aclose)
        host = GameHost(saves_dir=settings.saves_dir)
        raw = await stack.enter_async_context(Client(build_server(host)))
        service = AgentService(
            Deps(GameClient(raw), decider, llm, agent_config(settings)),
            list_saves=partial(save_index, settings.saves_dir),
            owners=SaveOwners(settings.saves_dir, sessions),
        )
        stack.push_async_callback(service.aclose)
        yield service
