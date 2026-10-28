import asyncio
import json
import os
from datetime import UTC, datetime

import pytest
from mcp.client import Client
from pydantic import SecretStr

import gumshoe.api.wiring as wiring
import gumshoe.decider.backends.factory as factory
from gumshoe.agent import AgentConfig
from gumshoe.api import create_app
from gumshoe.api.games import MAX_TURN_CHARS
from gumshoe.api.service import AgentService, Caps
from gumshoe.api.wiring import (
    agent_config,
    default_service,
    housekeeping,
    save_index,
    thirty_five_days_ago,
)
from gumshoe.config import Settings
from gumshoe.decider import BudgetDecider, DeciderConfigError
from gumshoe.mcp_server import GameHost
from gumshoe.mcp_server.host import MAX_TEXT
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script, ScriptedDecider, ScriptedLlm
from tests.api.client import TestClient
from tests.api.helpers import OWNER
from tests.mcp_server.helpers import SeqIds
from tests.stats.factories import make_record


def test_default_settings_give_the_default_agent_config():
    assert agent_config(Settings(_env_file=None)) == AgentConfig()


def test_every_agent_setting_reaches_the_config(monkeypatch):
    monkeypatch.setenv("CONFIDENCE_GATE", "0.7")
    monkeypatch.setenv("CONFIRM_GATE", "0.9")
    monkeypatch.setenv("MAX_REDRAFTS", "1")
    monkeypatch.setenv("DRAMATIC_FROM", "3")
    monkeypatch.setenv("PERSONA_MODEL_DEFAULT", "a")
    monkeypatch.setenv("PERSONA_MODEL_DRAMATIC", "b")
    monkeypatch.setenv("TURN_TIMEOUT_S", "30")
    config = agent_config(Settings(_env_file=None))
    assert config == AgentConfig(
        confidence_gate=0.7,
        confirm_gate=0.9,
        max_redrafts=1,
        dramatic_from=3.0,
        model_default="a",
        model_dramatic="b",
        turn_timeout_s=30.0,
    )


async def test_default_service_without_a_jev_key_raises_before_building_anything(tmp_path):
    settings = Settings(_env_file=None, jev_api_key=SecretStr(""))
    store = SqliteStatsStore(tmp_path / "d.db")
    with pytest.raises(DeciderConfigError):
        async with default_service(store, settings):
            raise AssertionError("must not get here")


async def test_default_service_stops_its_maintenance_task_on_exit(tmp_path):
    settings = Settings(
        _env_file=None, decider_primary="nimble", decider_shadow=None, saves_dir=tmp_path
    )
    store = SqliteStatsStore(tmp_path / "d.db")

    def maintaining() -> list[asyncio.Task[object]]:
        return [
            t
            for t in asyncio.all_tasks()
            if getattr(t.get_coro(), "__qualname__", "") == "AgentService.maintain"
        ]

    before = len(asyncio.all_tasks())
    async with default_service(store, settings):
        assert len(maintaining()) == 1
    await asyncio.sleep(0)
    assert maintaining() == []
    assert len(asyncio.all_tasks()) == before


async def test_default_service_expires_games_after_the_configured_idle_time(tmp_path):
    settings = Settings(
        _env_file=None,
        decider_primary="nimble",
        decider_shadow=None,
        saves_dir=tmp_path,
        game_idle_minutes=2,
    )
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        assert service._idle_s == 120.0


async def test_default_service_builds_a_working_service_with_nimble_only(tmp_path):
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow=None)
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        new = await service.new_game(1, owner=OWNER)
        state = await service.state(new.game, owner=OWNER)
        assert state.brief == new.brief
        await service.delete_game(new.game, owner=OWNER)


def test_the_default_app_without_a_key_serves_stats_and_503s_games(tmp_path):
    settings = Settings(_env_file=None, jev_api_key=SecretStr(""))
    app = create_app(SqliteStatsStore(tmp_path / "d.db"), settings=settings)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        response = client.post("/api/games", json={"seed": 1})
    assert response.status_code == 503 and response.json()["code"] == "unavailable"


def test_the_default_app_with_nimble_only_creates_a_game(tmp_path):
    settings = Settings(
        _env_file=None, decider_primary="nimble", decider_shadow=None, saves_dir=tmp_path
    )
    app = create_app(SqliteStatsStore(tmp_path / "d.db"), settings=settings)
    with TestClient(app) as client:
        response = client.post("/api/games", json={"seed": 1})
        assert response.status_code == 200
        assert client.delete(f"/api/games/{response.json()['game']}").status_code == 204


async def test_default_service_records_into_the_store_and_closes_in_order(tmp_path, monkeypatch):
    """No network: the decider and the Ollama client are fakes. Pins spec 3.3: the injected
    store is the recorder; on exit the turns stop, then the MCP client, decider and Ollama."""

    log: list[str] = []
    seen: dict[str, object] = {}

    class Decider(ScriptedDecider):
        async def aclose(self) -> None:
            log.append("decider")

    class Llm(ScriptedLlm):
        async def aclose(self) -> None:
            log.append("llm")

    def make_decider(settings, *, recorder=None, ledger=None):
        seen["recorder"] = recorder
        seen["ledger"] = ledger
        return Decider(Script())

    def ollama(base_url, *, timeout):
        seen["ollama"] = (base_url, timeout)
        return Llm([])

    class TracedClient(Client):
        async def __aexit__(self, *exc_info):
            log.append("client")
            return await super().__aexit__(*exc_info)

    real_aclose = AgentService.aclose

    async def traced_aclose(self):
        log.append("service")
        await real_aclose(self)

    monkeypatch.setattr(wiring, "make_decider", make_decider)
    monkeypatch.setattr(wiring, "OllamaLlm", ollama)
    monkeypatch.setattr(wiring, "Client", TracedClient)
    monkeypatch.setattr(AgentService, "aclose", traced_aclose)
    settings = Settings(_env_file=None, ollama_base_url="http://ollama:1/v1", llm_timeout_s=7.0)
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        await service.new_game(1, owner=OWNER)
    assert seen == {"recorder": store, "ledger": store, "ollama": ("http://ollama:1/v1", 7.0)}
    assert log == ["service", "client", "decider", "llm"]


def test_the_agent_never_sends_the_server_more_text_than_it_accepts():
    assert agent_config(Settings(_env_file=None)).max_text <= MAX_TEXT  # drafts to check_reply
    assert MAX_TURN_CHARS <= MAX_TEXT  # the player's text to accusation_questions, check_reply


def test_the_save_index_lists_saves_newest_first_and_never_their_case(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    first = host.save_game(host.new_game(1).game).name
    second = host.save_game(host.new_game(2, "short").game).name
    os.utime(tmp_path / f"{first}.json", (1_000_000_000, 1_000_000_000))
    (tmp_path / "notes.json").write_text("{}")  # not a save name: ignored
    (tmp_path / "fedcba9876543210.json").write_text("not json")  # unreadable: left out
    listed = save_index(tmp_path, lambda name: True)
    assert [s.name for s in listed] == [second, first]
    assert {(s.pack, s.status) for s in listed} == {("castle", "playing")}
    assert listed[1].created_at == "2001-09-09T01:46:40+00:00"
    dumped = "".join(s.model_dump_json() for s in listed)
    assert "truth" not in dumped and "case" not in dumped


def test_a_save_of_a_pack_the_server_lacks_lists_by_its_id(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    name = host.save_game(host.new_game(1).game).name
    path = tmp_path / f"{name}.json"
    data = json.loads(path.read_text())
    data["pack"] = "gone"
    path.write_text(json.dumps(data))
    (listed,) = save_index(tmp_path, lambda n: True)
    assert (listed.pack, listed.setting) == ("gone", "gone")


def test_a_save_of_a_bundled_pack_lists_the_setting_title(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    host.save_game(host.new_game(1).game)
    (listed,) = save_index(tmp_path, lambda n: True)
    assert (listed.pack, listed.setting) == ("castle", "Castle")


def test_the_save_index_of_a_missing_folder_is_empty(tmp_path):
    assert save_index(tmp_path / "nowhere", lambda name: True) == []


async def test_default_service_saves_into_the_configured_folder(tmp_path):
    settings = Settings(
        _env_file=None, decider_primary="nimble", decider_shadow=None, saves_dir=tmp_path
    )
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        new = await service.new_game(1, owner=OWNER)
        saved = await service.save_game(new.game, owner=OWNER)
        listed = await service.saves(owner=OWNER)
    assert (tmp_path / f"{saved.name}.json").is_file()
    assert [s.name for s in listed] == [saved.name]


def test_the_save_index_skips_a_save_whose_state_nests_too_deeply_to_parse(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    good = host.save_game(host.new_game(1).game).name
    bad = host.save_game(host.new_game(2).game).name
    path = tmp_path / f"{bad}.json"
    data = json.loads(path.read_text())
    data["state"] = "[" * 100_000
    path.write_text(json.dumps(data))
    assert [s.name for s in save_index(tmp_path, lambda name: True)] == [good]


def test_the_save_index_leaves_out_saves_the_caller_does_not_own(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    mine = host.save_game(host.new_game(1).game).name
    host.save_game(host.new_game(2, "short").game)
    assert [s.name for s in save_index(tmp_path, lambda name: name == mine)] == [mine]
    assert save_index(tmp_path, lambda name: False) == []


async def test_default_service_applies_the_limit_settings(tmp_path):
    settings = Settings(
        _env_file=None,
        decider_primary="nimble",
        decider_shadow=None,
        saves_dir=tmp_path,
        session_games_open=2,
        max_parallel_turns=3,
        turn_queue_size=5,
    )
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        assert service._caps == Caps.from_settings(settings)
        assert service._gate is not None and (service._gate.parallel, service._gate.queue) == (3, 5)
        assert service._quotas is not None


async def test_default_service_resumes_the_jev_budget_before_serving_and_closes_it(
    tmp_path, monkeypatch
):
    """No network: the clients are fakes. The store is the usage ledger; today's count is read
    from it once before the service is handed out; on exit the metered Jev stack closes before
    Ollama."""
    log: list[str] = []
    made: dict[str, object] = {}

    class Closing(ScriptedDecider):
        def __init__(self, name):
            super().__init__(Script())
            self.name = name

        async def aclose(self) -> None:
            log.append(f"close {self.name}")

    real_make = wiring.make_decider

    def make_decider(settings, *, recorder=None, ledger=None):
        made["decider"] = real_make(settings, recorder=recorder, ledger=ledger)
        return made["decider"]

    class Llm(ScriptedLlm):
        async def aclose(self) -> None:
            log.append("llm")

    monkeypatch.setattr(factory, "_client", lambda settings, profile: Closing(profile.name))
    monkeypatch.setattr(wiring, "make_decider", make_decider)
    monkeypatch.setattr(wiring, "OllamaLlm", lambda base_url, *, timeout: Llm([]))
    settings = Settings(
        _env_file=None, jev_api_key=SecretStr("k"), jev_daily_tokens=100, saves_dir=tmp_path
    )
    store = SqliteStatsStore(tmp_path / "d.db")
    store.add_usage(
        datetime.now(UTC).date().isoformat(), "203.0.113.9", 100
    )  # today's cap already spent
    reads: list[str] = []
    real_totals = store.usage_totals
    monkeypatch.setattr(store, "usage_totals", lambda day: reads.append(day) or real_totals(day))
    async with default_service(store, settings):
        decider = made["decider"]
        assert isinstance(decider, BudgetDecider)
        assert len(reads) == 1 and decider.mode == "slow"
    assert len(reads) == 1
    # the Jev primary and its shadow close first, then Nimble alone, then the Ollama client
    assert log == ["close jev", "close nimble", "close nimble", "llm"]


def test_the_usage_cutoff_is_35_days_back_as_a_zero_padded_iso_day():
    assert thirty_five_days_ago(datetime(2026, 2, 10, 23, 59, tzinfo=UTC)) == "2026-01-06"
    assert thirty_five_days_ago(datetime(2026, 3, 5, 0, 0, tzinfo=UTC)) == "2026-01-29"
    assert thirty_five_days_ago(datetime(2026, 1, 20, tzinfo=UTC)) == "2025-12-16"


def _decision_store(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert(
        [
            make_record(decision_id="old", ts="2026-08-17T00:00:00.000000+00:00"),
            make_record(decision_id="mid", ts="2026-09-06T00:00:00.000000+00:00"),
            make_record(decision_id="new", ts="2026-10-11T00:00:00.000000+00:00"),
        ]
    )
    store.add_usage("2026-08-01", "k", 5)
    store.add_usage("2026-10-15", "k", 5)
    return store


NOW = lambda: datetime(2026, 10, 16, tzinfo=UTC)  # noqa: E731


def test_housekeeping_purges_old_usage_and_decisions(tmp_path):
    store = _decision_store(tmp_path)
    housekeeping(store, 30, now=NOW)()
    assert store.fetch_decisions(["old"]) == []
    assert store.fetch_decisions(["mid"]) == []  # 40 days old
    assert len(store.fetch_decisions(["new"])) == 1
    assert store.usage_totals("2026-08-01") == {}
    assert store.usage_totals("2026-10-15") == {"k": 5}


def test_zero_retention_never_calls_the_decision_purge(tmp_path):
    store = _decision_store(tmp_path)
    calls: list[datetime] = []
    store.purge_decisions = calls.append  # type: ignore[method-assign, assignment]
    housekeeping(store, 0, now=NOW)()
    assert calls == []
    assert store.usage_totals("2026-08-01") == {}  # the usage purge still ran
    assert len(store.fetch_decisions(["old"])) == 1


def test_a_failing_decision_purge_does_not_skip_the_usage_purge(tmp_path, caplog):
    store = _decision_store(tmp_path)

    def boom(_: datetime) -> int:
        raise RuntimeError("secret detail")

    store.purge_decisions = boom  # type: ignore[method-assign]
    housekeeping(store, 30, now=NOW)()  # does not raise
    assert store.usage_totals("2026-08-01") == {}
    assert "RuntimeError" in caplog.text and "secret detail" not in caplog.text


def test_a_failing_usage_purge_does_not_skip_the_decision_purge(tmp_path, caplog):
    store = _decision_store(tmp_path)

    def boom(_: str) -> int:
        raise RuntimeError("x")

    store.purge_usage = boom  # type: ignore[method-assign]
    housekeeping(store, 30, now=NOW)()
    assert store.fetch_decisions(["old"]) == []
