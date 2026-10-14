import os

import pytest
from mcp.client import Client
from pydantic import SecretStr
from starlette.testclient import TestClient

import gumshoe.api.wiring as wiring
from gumshoe.agent import AgentConfig
from gumshoe.api import create_app
from gumshoe.api.games import MAX_TURN_CHARS
from gumshoe.api.service import AgentService
from gumshoe.api.wiring import agent_config, default_service, save_index
from gumshoe.config import Settings
from gumshoe.decider import DeciderConfigError
from gumshoe.mcp_server import GameHost
from gumshoe.mcp_server.host import MAX_TEXT
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script, ScriptedDecider, ScriptedLlm
from tests.mcp_server.helpers import SeqIds


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


async def test_default_service_builds_a_working_service_with_nimble_only(tmp_path):
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow=None)
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        new = await service.new_game(1)
        state = await service.state(new.game)
        assert state.brief == new.brief
        await service.delete_game(new.game)


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

    def make_decider(settings, *, recorder=None):
        seen["recorder"] = recorder
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
        await service.new_game(1)
    assert seen == {"recorder": store, "ollama": ("http://ollama:1/v1", 7.0)}
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
    listed = save_index(tmp_path)
    assert [s.name for s in listed] == [second, first]
    assert {(s.pack, s.status) for s in listed} == {("castle", "playing")}
    assert listed[1].created_at == "2001-09-09T01:46:40+00:00"
    dumped = "".join(s.model_dump_json() for s in listed)
    assert "truth" not in dumped and "case" not in dumped


def test_the_save_index_of_a_missing_folder_is_empty(tmp_path):
    assert save_index(tmp_path / "nowhere") == []


async def test_default_service_saves_into_the_configured_folder(tmp_path):
    settings = Settings(
        _env_file=None, decider_primary="nimble", decider_shadow=None, saves_dir=tmp_path
    )
    store = SqliteStatsStore(tmp_path / "d.db")
    async with default_service(store, settings) as service:
        new = await service.new_game(1)
        saved = await service.save_game(new.game)
        listed = await service.saves()
    assert (tmp_path / f"{saved.name}.json").is_file()
    assert [s.name for s in listed] == [saved.name]
