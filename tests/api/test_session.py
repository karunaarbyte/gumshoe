import logging

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import TestClient

from gumshoe.api.errors import UNKNOWN_GAME
from gumshoe.api.session import NewOwner, Owner, Sessions
from gumshoe.config import Settings

SECRET = b"k" * 32


def test_a_cookie_round_trips_to_its_session_id():
    s = Sessions(SECRET, secure=False)
    sid, value = s.issue()
    assert s.read(value) == sid and len(sid) == 22


def test_two_issues_differ():
    s = Sessions(SECRET, secure=False)
    assert s.issue()[0] != s.issue()[0]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "nodot",
        "a.b.c",
        ".",
        "é.é",
        "x" * 5000,
        "AAAAAAAAAAAAAAAAAAAAAA.",
        "AAAAAAAAAAAAAAAAAAAAAA." + "0" * 64,
    ],
)
def test_anything_that_is_not_a_valid_cookie_reads_as_no_session(bad):
    assert Sessions(SECRET, secure=False).read(bad) is None


def test_a_tampered_id_or_signature_is_refused():
    s = Sessions(SECRET, secure=False)
    sid, value = s.issue()
    other = "B" * 22
    assert s.read(f"{other}.{value.split('.')[1]}") is None
    sig = value.split(".")[1]
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert s.read(f"{sid}.{flipped}") is None


def test_another_secret_does_not_read_the_cookie():
    _, value = Sessions(SECRET, secure=False).issue()
    assert Sessions(b"z" * 32, secure=False).read(value) is None


def test_the_owner_tag_is_stable_and_not_the_cookie_signature():
    s = Sessions(SECRET, secure=False)
    sid, value = s.issue()
    assert s.owner_tag(sid) == s.owner_tag(sid) and len(s.owner_tag(sid)) == 32
    assert s.owner_tag(sid) != value.split(".")[1][:32]
    assert Sessions(b"z" * 32, secure=False).owner_tag(sid) != s.owner_tag(sid)


def test_public_mode_uses_the_host_prefix_and_secure():
    assert Sessions(SECRET, secure=True).cookie_name == "__Host-gs_session"
    assert Sessions(SECRET, secure=False).cookie_name == "gs_session"


def app_with(sessions: Sessions) -> FastAPI:
    app = FastAPI()
    app.state.sessions = sessions

    @app.post("/new")
    def new(owner: NewOwner) -> dict[str, str]:
        return {"owner": owner}

    @app.get("/who")
    def who(owner: Owner) -> dict[str, str]:
        return {"owner": owner}

    @app.get("/open")
    def open_() -> dict[str, str]:
        return {"ok": "yes"}

    from fastapi.responses import JSONResponse

    from gumshoe.agent import ToolFailure
    from gumshoe.api.errors import error_body, status_for

    @app.exception_handler(ToolFailure)
    def failure(request, exc):
        return JSONResponse(error_body(exc.code, exc.message), status_code=status_for(exc.code))

    return app


def test_new_owner_sets_a_httponly_samesite_cookie_and_reuses_it():
    app = app_with(Sessions(SECRET, secure=False))
    with TestClient(app) as client:
        first = client.post("/new")
        header = first.headers["set-cookie"]
        assert "gs_session=" in header and "HttpOnly" in header and "SameSite=lax" in header
        assert "Max-Age=2592000" in header and "Path=/" in header and "Secure" not in header
        second = client.post("/new")
        assert second.json() == first.json()
        assert "set-cookie" not in second.headers  # an existing session is not re-issued


def test_public_mode_cookie_is_secure_and_host_prefixed():
    app = app_with(Sessions(SECRET, secure=True))
    with TestClient(app, base_url="https://gumshoe.example.com") as client:
        header = client.post("/new").headers["set-cookie"]
    assert header.startswith("__Host-gs_session=") and "Secure" in header and "Domain" not in header


def test_current_owner_without_a_valid_session_is_unknown_game():
    app = app_with(Sessions(SECRET, secure=False))
    with TestClient(app) as client:
        r = client.get("/who")
        assert (r.status_code, r.json()) == (404, {"code": "unknown_game", "message": UNKNOWN_GAME})
        client.cookies.set("gs_session", "garbage")
        assert client.get("/who").status_code == 404
        client.post("/new")
        assert client.get("/who").status_code == 200


def test_a_route_without_the_dependency_never_sets_a_cookie():
    app = app_with(Sessions(SECRET, secure=False))
    with TestClient(app) as client:
        assert "set-cookie" not in client.get("/open").headers


def test_from_settings_generates_a_secret_with_a_warning_outside_public_mode(caplog):
    with caplog.at_level(logging.WARNING):
        s = Sessions.from_settings(Settings(_env_file=None))
    assert s.secure is False and "SESSION_SECRET" in caplog.text
    sid, value = s.issue()
    assert s.read(value) == sid


def test_from_settings_uses_the_configured_secret_and_public_mode():
    settings = Settings(
        _env_file=None,
        public_origin="https://gumshoe.example.com",
        session_secret=SecretStr("s" * 32),
    )
    a, b = Sessions.from_settings(settings), Sessions.from_settings(settings)
    assert a.secure is True and a.read(b.issue()[1]) is not None
