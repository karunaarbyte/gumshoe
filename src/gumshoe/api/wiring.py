"""Builds the real agent service from settings. The only api module that touches the MCP SDK."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from mcp.client import Client

from gumshoe.agent import AgentConfig, Deps, GameClient, OllamaLlm
from gumshoe.api.ratelimit import Quotas, TurnGate
from gumshoe.api.saveowners import SaveOwners
from gumshoe.api.service import AgentService, Caps, SaveSummary
from gumshoe.api.session import Sessions
from gumshoe.config import Settings, get_settings
from gumshoe.decider import BudgetDecider, make_decider
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


def thirty_five_days_ago(now: datetime | None = None) -> str:
    """The UTC day (YYYY-MM-DD) 35 days back: usage rows older than it are purged."""
    return ((now or datetime.now(UTC)) - timedelta(days=35)).strftime("%Y-%m-%d")


@asynccontextmanager
async def default_service(
    store: SqliteStatsStore,
    settings: Settings | None = None,
    sessions: Sessions | None = None,
    quotas: Quotas | None = None,
) -> AsyncIterator[AgentService]:
    """The service the app runs on. The injected store doubles as the decision recorder and the
    Jev usage ledger (never a second store on the same file); a Jev budget resumes today's count
    from it before serving. A missing Jev key raises `DeciderConfigError` before anything is
    opened. On exit: turns are cancelled, then the MCP client closes, then the decider (so
    background records and usage counts drain), then the Ollama client. `quotas` is the app's own
    (shared with its middleware); a fresh one is made when none is given. The maintenance loop
    (idle-game expiry, save purge) runs as a task for the service's life and stops first."""
    settings = settings or get_settings()
    sessions = sessions or Sessions.from_settings(settings)
    quotas = quotas or Quotas(settings)
    gate = TurnGate(
        settings.max_parallel_turns, settings.turn_queue_size, settings.turn_queue_wait_s
    )
    decider = make_decider(settings, recorder=store, ledger=store)
    llm = OllamaLlm(settings.ollama_base_url, timeout=settings.llm_timeout_s)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(llm.aclose)
        stack.push_async_callback(decider.aclose)  # flushes the Jev usage counts, too
        if isinstance(decider, BudgetDecider):
            await decider.load()  # today's Jev spend so far, read once before serving
        host = GameHost(saves_dir=settings.saves_dir, max_games=settings.effective_max_games)
        raw = await stack.enter_async_context(Client(build_server(host)))
        service = AgentService(
            Deps(GameClient(raw), decider, llm, agent_config(settings)),
            list_saves=partial(save_index, settings.saves_dir),
            owners=SaveOwners(settings.saves_dir, sessions),
            quotas=quotas,
            gate=gate,
            caps=Caps.from_settings(settings),
            clock=time.monotonic,
            idle_s=settings.game_idle_minutes * 60.0,
        )
        stack.push_async_callback(service.aclose)
        maintenance = asyncio.create_task(
            service.maintain(
                retention_s=settings.save_retention_days * 86400.0,
                housekeeping=lambda: store.purge_usage(thirty_five_days_ago()),
            )
        )

        async def stop_maintenance() -> None:
            maintenance.cancel()
            await asyncio.gather(maintenance, return_exceptions=True)

        stack.push_async_callback(stop_maintenance)  # runs before service.aclose
        yield service
