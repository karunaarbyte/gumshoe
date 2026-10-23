"""The app's HTTP surface outside the game itself: error bodies, the body cap, CORS, health and
meta."""

from contextlib import asynccontextmanager

import pytest
from pydantic import SecretStr

from gumshoe.api import create_app
from gumshoe.cases.play.state import MAX_ATTEMPTS
from gumshoe.config import Settings
from gumshoe.decider import DeciderConfigError
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory

CAP = 1024  # the smallest MAX_BODY_BYTES the settings accept
TOKEN = "t" * 40
ADMIN = {"authorization": "Bearer " + TOKEN}


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


async def personas_up():
    return True


def app_for(store, *, personas=personas_up, **settings):
    settings.setdefault("admin_token", SecretStr(TOKEN))
    return create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, **settings),
        personas_up=personas,
    )


# --- one error shape -----------------------------------------------------------------------------


def test_framework_errors_have_the_same_code_and_message_shape(store):
    with TestClient(app_for(store)) as client:
        missing = client.get("/api/nope")
        wrong = client.put("/api/games")
        bad_json = client.post(
            "/api/games", content=b"{not json", headers={"content-type": "application/json"}
        )
        bad_query = client.get("/api/decisions", params={"limit": "lots"}, headers=ADMIN)
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    assert (wrong.status_code, wrong.json()["code"]) == (405, "method_not_allowed")
    assert "allow" in wrong.headers  # the 405's own header survives
    for response in (bad_json, bad_query):
        assert response.status_code == 422
        assert set(response.json()) == {"code", "message"}
        assert response.json()["code"] == "bad_request"
    assert "limit" in bad_query.json()["message"]


def test_a_validation_message_never_repeats_the_input(store):
    with TestClient(app_for(store)) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        secret = "my-private-words " * 70  # over 1000 characters
        response = client.post(f"/api/games/{game}/turn", json={"text": secret})
    assert response.status_code == 422
    assert "my-private-words" not in response.text and "text" in response.json()["message"]


# --- the body cap --------------------------------------------------------------------------------


def big_body() -> bytes:
    return b'{"seed": 1, "preset": "' + b"x" * (2 * CAP) + b'"}'


def test_a_body_over_the_cap_is_413_by_its_length(store):
    with TestClient(app_for(store, max_body_bytes=CAP)) as client:
        response = client.post(
            "/api/games", content=big_body(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 413
    assert response.json() == {"code": "too_large", "message": "the request body is too large"}


def test_a_declared_length_over_the_cap_is_refused_before_anything_is_read(store):
    with TestClient(app_for(store, max_body_bytes=CAP)) as client:
        # /api/meta never reads a body, so only the Content-Length check can refuse this
        response = client.request("GET", "/api/meta", content=big_body())
    assert response.status_code == 413


def test_a_chunked_body_over_the_cap_is_413_while_it_is_read(store):
    def chunks():
        body = big_body()
        yield body[:20]
        yield body[20:]

    with TestClient(app_for(store, max_body_bytes=CAP)) as client:
        response = client.post(
            "/api/games", content=chunks(), headers={"content-type": "application/json"}
        )
    assert response.request.headers.get("transfer-encoding") == "chunked"
    assert response.status_code == 413 and response.json()["code"] == "too_large"


def test_a_body_under_the_cap_is_served(store):
    with TestClient(app_for(store, max_body_bytes=CAP)) as client:
        assert client.post("/api/games", json={"seed": 1}).status_code == 200


# --- CORS ----------------------------------------------------------------------------------------

PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


def test_cors_answers_only_the_listed_origins(store):
    app = app_for(store, cors_origins="http://localhost:5173, http://127.0.0.1:5173")
    with TestClient(app) as client:
        listed = client.options(
            "/api/games", headers={"Origin": "http://localhost:5173", **PREFLIGHT}
        )
        other = client.options("/api/games", headers={"Origin": "http://evil.test", **PREFLIGHT})
        simple = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert listed.status_code == 200
    assert listed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in other.headers
    assert simple.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_no_cors_origins_means_no_cors_at_all(store):
    with TestClient(app_for(store)) as client:
        preflight = client.options(
            "/api/games", headers={"Origin": "http://localhost:5173", **PREFLIGHT}
        )
    assert preflight.status_code == 405  # same origin only: use the Vite proxy in development
    assert "access-control-allow-origin" not in preflight.headers


# --- health and meta -----------------------------------------------------------------------------


def test_health_says_the_game_is_on_and_which_backends_and_models_serve_it(store):
    with TestClient(app_for(store, jev_api_key=SecretStr("sk-very-secret"))) as client:
        response = client.get("/api/health")
    assert response.json() == {
        "status": "ok",
        "game": "on",
        "reason": None,
        "primary": "jev",
        "shadow": "nimble",
        "persona_models": {"default": "ministral-3:14b", "dramatic": "gemma4:12b"},
        "personas": "up",
        "mode": "normal",
    }
    assert "sk-very-secret" not in response.text


def test_health_says_when_the_persona_models_are_down(store):
    async def down():
        return False

    with TestClient(app_for(store, personas=down, jev_api_key=SecretStr("sk"))) as client:
        body = client.get("/api/health").json()
    # the game still runs (suspects fall back to stock lines), but a UI can say so
    assert (body["game"], body["personas"]) == ("on", "down")


def test_health_says_why_the_game_is_off(store):
    @asynccontextmanager
    async def factory(_store):
        raise DeciderConfigError("jev", "JEV_API_KEY is not set (add it to .env)")
        yield  # pragma: no cover

    app = create_app(store, make_service=factory, settings=Settings(_env_file=None))
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert (body["status"], body["game"]) == ("ok", "off")
    assert "JEV_API_KEY is not set" in body["reason"]


def test_meta_gives_the_numbers_a_ui_would_otherwise_hard_code(store):
    with TestClient(app_for(store)) as client:
        body = client.get("/api/meta").json()
    assert body == {
        "presets": ["short", "standard", "long"],
        "default_preset": "standard",
        "max_attempts": MAX_ATTEMPTS,
        "max_turn_chars": 1000,
    }
