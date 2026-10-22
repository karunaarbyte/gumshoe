from contextlib import asynccontextmanager

from gumshoe.api import create_app
from gumshoe.decider import DeciderConfigError
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory


def test_the_factory_is_entered_at_startup_and_exited_at_shutdown(tmp_path):
    log = []

    @asynccontextmanager
    async def factory(store):
        inner = fake_factory(Script())
        log.append("enter")
        async with inner(store) as service:
            yield service
        log.append("exit")

    app = create_app(SqliteStatsStore(tmp_path / "d.db"), make_service=factory)
    with TestClient(app) as client:
        assert log == ["enter"]
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
    assert log == ["enter", "exit"]


def test_no_jev_key_means_503_for_games_and_stats_still_work(tmp_path):
    @asynccontextmanager
    async def factory(store):
        raise DeciderConfigError("jev", "JEV_API_KEY is not set")
        yield  # pragma: no cover

    app = create_app(SqliteStatsStore(tmp_path / "d.db"), make_service=factory)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/decisions").json() == []
        for method, path, body in [
            ("post", "/api/games", {"seed": 1}),
            ("post", "/api/games/load", {"name": "0123456789abcdef"}),
            ("get", "/api/games/x", None),
            ("post", "/api/games/x/turn", {"text": "hi"}),
            ("post", "/api/games/x/save", None),
            ("delete", "/api/games/x", None),
        ]:
            response = getattr(client, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 503, path
            assert response.json()["code"] == "unavailable"


def test_without_a_lifespan_the_game_endpoints_are_503(tmp_path):
    app = create_app(SqliteStatsStore(tmp_path / "d.db"), make_service=fake_factory(Script()))
    client = TestClient(app)  # not entered: the lifespan never runs
    assert client.post("/api/games", json={"seed": 1}).status_code == 503


def test_another_startup_error_is_not_swallowed(tmp_path):
    @asynccontextmanager
    async def factory(store):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    app = create_app(SqliteStatsStore(tmp_path / "d.db"), make_service=factory)
    try:
        with TestClient(app):
            raise AssertionError("startup should have failed")
    except RuntimeError as exc:
        assert str(exc) == "boom"


def test_a_503_body_never_names_the_key_or_a_traceback(tmp_path):
    @asynccontextmanager
    async def factory(store):
        raise DeciderConfigError("jev", "JEV_API_KEY is not set")
        yield  # pragma: no cover

    app = create_app(SqliteStatsStore(tmp_path / "d.db"), make_service=factory)
    with TestClient(app) as client:
        text = client.post("/api/games", json={"seed": 1}).text
    assert "JEV_API_KEY" not in text and "Traceback" not in text


def test_with_the_shadow_run_off_the_game_runs_on_nimble_alone_with_no_jev_key(tmp_path):
    from gumshoe.config import Settings

    settings = Settings(_env_file=None, shadow_run=False, saves_dir=tmp_path / "saves")
    app = create_app(SqliteStatsStore(tmp_path / "d.db"), settings=settings)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert (health["game"], health["primary"], health["shadow"]) == ("on", "nimble", None)
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
