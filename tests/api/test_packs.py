"""The API takes a pack, reports the packs, and refuses a bad one before charging any quota."""

import pytest

import gumshoe.api.__main__ as entry
from gumshoe.api import create_app
from gumshoe.api.ratelimit import Quotas
from gumshoe.api.service import Caps
from gumshoe.cases import BuiltinPackError, bundled_packs
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def client_for(store, **kw):
    return TestClient(create_app(store, make_service=fake_factory(Script(), **kw)))


def test_meta_lists_the_packs(store):
    with client_for(store) as client:
        body = client.get("/api/meta").json()
    castle = next(p for p in body["packs"] if p["id"] == "castle")
    assert set(castle) == {"id", "title", "blurb", "presets"}
    assert "standard" in castle["presets"]
    expected = [p.model_dump() | {"presets": list(p.presets)} for p in bundled_packs()]
    assert body["packs"] == expected
    assert body["default_preset"] == "standard" and body["presets"] == castle["presets"]


def test_a_new_game_says_its_pack_and_preset(store):
    with client_for(store) as client:
        body = client.post("/api/games", json={"seed": 1}).json()
    assert (body["pack"], body["preset"]) == ("castle", "standard")


@pytest.mark.parametrize("pack_id", [p.id for p in bundled_packs()])
def test_every_bundled_pack_makes_a_real_game(store, pack_id):
    with client_for(store) as client:
        response = client.post("/api/games", json={"seed": 1, "pack": pack_id})
    assert response.status_code == 200 and response.json()["pack"] == pack_id


def test_an_unknown_pack_is_refused_without_echoing_it(store):
    with client_for(store) as client:
        response = client.post("/api/games", json={"seed": 1, "pack": "nope"})
    assert response.status_code == 422
    assert response.json() == {"code": "bad_argument", "message": "unknown setting"}
    assert "nope" not in response.text


@pytest.mark.parametrize("pack", ["Castle", "../x", "", "a" * 33])
def test_a_malformed_pack_fails_the_pattern(store, pack):
    with client_for(store) as client:
        response = client.post("/api/games", json={"seed": 1, "pack": pack})
    assert response.status_code == 422 and response.json()["code"] == "bad_request"


@pytest.mark.parametrize("bad", [{"pack": "nope"}, {"preset": "nonesuch"}])
def test_a_refused_request_charges_no_open_game_quota(store, bad):
    with client_for(store, caps=Caps(games_per_session=2)) as client:
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
        assert client.post("/api/games", json={"seed": 2, **bad}).status_code == 422
        # had the refusal been charged (or held a slot), this second game would hit the cap
        assert client.post("/api/games", json={"seed": 3}).status_code == 200
        assert client.post("/api/games", json={"seed": 4}).status_code == 429


@pytest.mark.parametrize("bad", [{"pack": "nope"}, {"preset": "nonesuch"}])
def test_a_bad_request_at_the_open_game_cap_is_422_not_429(store, bad):
    with client_for(store, caps=Caps(games_per_session=1)) as client:
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
        # validation runs before admission: the cap does not hide the real error
        assert client.post("/api/games", json={"seed": 2, **bad}).status_code == 422
        assert client.post("/api/games", json={"seed": 3}).status_code == 429


@pytest.mark.parametrize("bad", [{"pack": "nope"}, {"preset": "nonesuch"}])
def test_a_refused_request_charges_no_creation_rate(store, bad):
    quotas = Quotas(Settings(_env_file=None, session_games_per_hour=2))
    with client_for(store, quotas=quotas) as client:
        # one session throughout: a valid game, the refusal, a valid game. Charged, the refusal
        # would use the second slot and the last request would be rate limited.
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
        assert client.post("/api/games", json={"seed": 2, **bad}).status_code == 422
        assert client.post("/api/games", json={"seed": 3}).status_code == 200
        assert client.post("/api/games", json={"seed": 4}).status_code == 429


def test_an_unhosted_preset_is_refused_naming_the_hosted_ones(store):
    with client_for(store) as client:
        response = client.post("/api/games", json={"seed": 1, "preset": "nonesuch"})
    assert response.status_code == 422 and response.json()["code"] == "bad_argument"
    assert "standard" in response.json()["message"] and "nonesuch" not in response.json()["message"]


def test_a_load_says_the_real_pack_and_preset(store, tmp_path):
    with client_for(store, saves_dir=tmp_path / "saves") as client:
        game = client.post("/api/games", json={"seed": 1, "preset": "short"}).json()["game"]
        name = client.post(f"/api/games/{game}/save").json()["name"]
        loaded = client.post("/api/games/load", json={"name": name}).json()
    assert (loaded["pack"], loaded["preset"]) == ("castle", "short")


def test_a_broken_bundled_pack_stops_startup(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, stats_db_path=tmp_path / "d.db")
    monkeypatch.setattr(entry, "get_settings", lambda: settings)

    def broken():
        raise BuiltinPackError("bundled pack 'castle' has no title")

    monkeypatch.setattr(entry, "bundled_packs", broken)
    with pytest.raises(SystemExit, match="bundled pack 'castle' has no title"):
        entry.main([])


def test_open_games_name_their_setting_and_real_preset(store, tmp_path):
    with client_for(store, saves_dir=tmp_path / "saves") as client:
        client.post("/api/games", json={"seed": 1, "preset": "short"})
        (row,) = client.get("/api/games").json()
    assert (row["pack"], row["setting"], row["preset"]) == ("castle", "Castle", "short")


def test_a_loaded_game_keeps_its_real_preset(store, tmp_path):
    with client_for(store, saves_dir=tmp_path / "saves") as client:
        game = client.post("/api/games", json={"seed": 1, "preset": "short"}).json()["game"]
        saved = client.post(f"/api/games/{game}/save").json()["name"]
        loaded = client.post("/api/games/load", json={"name": saved}).json()
        assert (loaded["pack"], loaded["preset"]) == ("castle", "short")
        state = client.get(f"/api/games/{loaded['game']}").json()
        rows = client.get("/api/games").json()
    assert state["preset"] == "short"
    assert {r["preset"] for r in rows} == {"short"}
