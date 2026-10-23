import logging

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient as RawClient

from gumshoe.api import create_app
from gumshoe.api.service import Caps
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory

TOKEN = "t" * 40
SECRET_TEXT = "the-butler-did-it"


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def app_for(store, **settings):
    async def up():
        return True

    return create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, **settings),
        personas_up=up,
    )


def client_for(store, **settings):
    return TestClient(app_for(store, **settings))


def lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "gumshoe.api.refusals"]


def capture(caplog):
    return caplog.at_level(logging.INFO, logger="gumshoe.api.refusals")


# --- the brief's cases ---


def test_a_rate_limit_refusal_is_logged_with_code_route_and_ip(store, caplog):
    with capture(caplog), client_for(store, ip_requests_per_minute=1) as client:
        client.get("/api/meta")
        client.get("/api/meta")
    [line] = lines(caplog)
    assert line.startswith("refused code=rate_limited route=GET /api/meta ip=")
    assert "session=-" in line


def test_a_forbidden_origin_is_logged(store, caplog):
    with capture(caplog), client_for(store) as client:
        client.post("/api/games", json={"seed": 1}, headers={"origin": "http://evil.example"})
    [line] = lines(caplog)
    assert "code=forbidden" in line and "evil" not in line


def test_a_game_quota_refusal_logs_the_session_prefix_but_not_the_cookie_or_text(store, caplog):
    async def up():
        return True

    # service-level limits come from the service the factory builds, not from Settings
    app = create_app(
        store,
        make_service=fake_factory(Script(), caps=Caps(games_per_session=1)),
        settings=Settings(_env_file=None),
        personas_up=up,
    )
    with TestClient(app) as client:
        client.post("/api/games", json={"seed": 1})
        cookie = client.cookies.get("gs_session")
        with capture(caplog):
            client.post("/api/games", json={"seed": 2})
    [line] = lines(caplog)
    assert "code=quota" in line and f"session={cookie[:6]}" in line and cookie not in line
    assert cookie.split(".")[1] not in line  # nor the signature


def test_ordinary_not_found_answers_are_not_refusals(store, caplog):
    with capture(caplog), client_for(store) as client:
        client.get("/api/nope")
        client.get("/api/games/0123456789abcdef")
    assert lines(caplog) == []


# --- the other refusals of the safety layer ---


def test_a_body_that_is_not_json_is_logged_once(store, caplog):
    with capture(caplog), client_for(store) as client:
        r = client.post(
            "/api/games", content=SECRET_TEXT.encode(), headers={"content-type": "text/plain"}
        )
    assert r.status_code == 415
    [line] = lines(caplog)
    assert line.startswith("refused code=bad_request route=POST /api/games ip=")
    assert SECRET_TEXT not in line


def test_a_body_too_large_by_its_length_is_logged_once(store, caplog):
    with capture(caplog), client_for(store, max_body_bytes=1024) as client:
        r = client.post("/api/games", json={"seed": 1, "text": SECRET_TEXT * 100})
    assert r.status_code == 413
    [line] = lines(caplog)
    assert line.startswith("refused code=too_large route=POST /api/games ip=")
    assert SECRET_TEXT not in line


def test_a_chunked_body_too_large_is_logged_once(store, caplog):
    def chunks():
        yield b'{"seed": 1, "text": "'
        yield SECRET_TEXT.encode() * 100
        yield b'"}'

    with capture(caplog), client_for(store, max_body_bytes=1024) as client:
        r = client.post(
            "/api/games", content=chunks(), headers={"content-type": "application/json"}
        )
    assert r.status_code == 413
    [line] = lines(caplog)
    assert line.startswith("refused code=too_large route=POST /api/games ip=")
    assert SECRET_TEXT not in line


def test_an_ordinary_validation_error_is_not_a_refusal(store, caplog):
    with capture(caplog), client_for(store) as client:
        r = client.post("/api/games", json={"seed": "not a number"})
    assert r.status_code == 422
    assert lines(caplog) == []


def test_an_answered_request_is_not_logged(store, caplog):
    with capture(caplog), client_for(store) as client:
        assert client.post("/api/games", json={"seed": 1}).status_code == 200
        assert client.get("/api/meta").status_code == 200
    assert lines(caplog) == []


# --- what the line must never carry ---


def test_the_query_string_is_never_logged(store, caplog):
    with capture(caplog), client_for(store, ip_requests_per_minute=1) as client:
        client.get("/api/meta?token=q-secret-1")
        client.get("/api/meta?token=q-secret-2&text=" + SECRET_TEXT)
    [line] = lines(caplog)
    assert "route=GET /api/meta ip=" in line
    assert "q-secret" not in line and SECRET_TEXT not in line and "?" not in line


def test_the_authorization_header_and_cookie_header_are_never_logged(store, caplog):
    headers = {"authorization": f"Bearer {TOKEN}", "cookie": "gs_session=abcdefghijk.0123; x=y"}
    with capture(caplog), client_for(store, ip_requests_per_minute=1) as client:
        client.get("/api/meta", headers=headers)
        client.get("/api/meta", headers=headers)
    [line] = lines(caplog)
    assert TOKEN not in line and "Bearer" not in line
    assert "abcdefghijk" not in line and "0123" not in line and "session=abcdef" in line


def test_a_forbidden_body_is_never_logged(store, caplog):
    with capture(caplog), RawClient(app_for(store)) as client:  # no origin at all
        client.post("/api/games", json={"seed": 1, "text": SECRET_TEXT})
    [line] = lines(caplog)
    assert "code=forbidden" in line and SECRET_TEXT not in line


def test_a_hostile_path_cannot_forge_a_log_line(store, caplog):
    with capture(caplog), RawClient(app_for(store)) as client:
        client.post("/api/x%0Arefused%20code=fake%0D%1B[31m", json={"seed": 1})
    [line] = lines(caplog)
    assert "\n" not in line and "\r" not in line and "\x1b" not in line
    assert line.count("code=") == 2 and line.startswith("refused code=forbidden route=POST ")
    assert " code=fake" not in line  # the space is replaced too: no field can be faked


def test_a_huge_path_is_capped(store, caplog):
    with capture(caplog), RawClient(app_for(store)) as client:
        client.post("/api/" + "a" * 5000, json={"seed": 1})
    [line] = lines(caplog)
    assert len(line) < 400 and "a" * 201 not in line


# --- admin routes keep their own, address-only line ---


def bearer(token=TOKEN):
    return {"authorization": f"Bearer {token}"}


def test_an_admin_refusal_is_logged_by_the_gate_only(store, caplog):
    with (
        caplog.at_level(logging.INFO),
        client_for(store, admin_token=SecretStr(TOKEN)) as client,
    ):
        assert client.get("/api/admin/usage", headers=bearer("wrong")).status_code == 404
        assert client.post("/api/admin/usage", json={}).status_code == 404  # 405 path
    assert lines(caplog) == []
    admin = [r.getMessage() for r in caplog.records if r.name == "gumshoe.api.admin"]
    assert admin == ["admin refused ip=testclient"] * 2


@pytest.mark.parametrize(
    "path", ["/api/stats/decisions", "/api/decisions", "/api/decisions/abc", "/api/admin/usage"]
)
def test_a_rate_limited_admin_route_logs_neither_route_nor_session(store, caplog, path):
    headers = {**bearer(), "cookie": "gs_session=abcdefghijk.0123"}
    settings = {"admin_token": SecretStr(TOKEN), "ip_requests_per_minute": 1}
    with capture(caplog), client_for(store, **settings) as client:
        client.get(path + "?q=1", headers=headers)
        assert client.get(path + "?q=2", headers=headers).status_code == 429
    assert lines(caplog) == ["refused code=rate_limited route=- ip=testclient session=-"]


def test_every_admin_route_is_masked(store):
    from fastapi.routing import APIRoute

    from gumshoe.api.admin import require_admin
    from gumshoe.api.refusals import admin_path

    app = app_for(store)
    gated = [
        route.path
        for route in app.router.routes
        if isinstance(route, APIRoute)
        and any(d.dependency is require_admin for d in route.dependencies)
    ]
    assert gated and all(admin_path(path) for path in gated)
    assert not admin_path("/api/games") and not admin_path("/api/meta")


# --- the helpers themselves ---


@pytest.mark.parametrize(
    ("cookie", "prefix"),
    [
        ("abcdefghijk.0123abcd", "abcdef"),
        ("abc.0123", "abc"),
        (None, "-"),
        ("", "-"),
        ("no-dot-here", "-"),
        ("a.b.c", "-"),
        (".sig", "-"),
        ("ab\ncdef.sig", "-"),
        ("ab cdef.sig", "-"),
    ],
)
def test_the_session_prefix_is_six_characters_of_the_id_or_a_dash(caplog, cookie, prefix):
    from gumshoe.api.refusals import log_refusal

    with capture(caplog):
        log_refusal("quota", "POST /api/games", "1.2.3.4", cookie)
    assert lines(caplog) == [
        f"refused code=quota route=POST /api/games ip=1.2.3.4 session={prefix}"
    ]


def test_every_field_is_sanitised(caplog):
    from gumshoe.api.refusals import log_refusal

    with capture(caplog):
        log_refusal("quo\nta", "GET /a\x00b‮c", "1.2\r.3.4", None)
    [line] = lines(caplog)
    assert line == "refused code=quo?ta route=GET /a?b?c ip=1.2?.3.4 session=-"


def test_logging_never_breaks_the_refusal(monkeypatch):
    from gumshoe.api import refusals

    def boom(*args, **kwargs):
        raise RuntimeError("the log is broken")

    monkeypatch.setattr(refusals.logger, "info", boom)
    refusals.log_refusal("quota", "GET /", "1.2.3.4", "abc.def")  # no exception
    refusals.log_refusal(None, None, None, 42)  # type: ignore[arg-type]


def test_a_broken_logger_still_answers_the_refusal(store, monkeypatch):
    from gumshoe.api import refusals

    def boom(*args, **kwargs):
        raise RuntimeError("the log is broken")

    monkeypatch.setattr(refusals.logger, "info", boom)
    with client_for(store, ip_requests_per_minute=1) as client:
        client.get("/api/meta")
        assert client.get("/api/meta").status_code == 429
    with client_for(store) as client:
        r = client.post("/api/games", json={"seed": 1}, headers={"origin": "http://evil"})
        assert r.status_code == 403


def test_a_malformed_cookie_header_gives_no_prefix(store, caplog):
    with capture(caplog), client_for(store, ip_requests_per_minute=1) as client:
        client.get("/api/meta")
        client.get("/api/meta", headers={"cookie": 'gs_session="abc\\'})
    [line] = lines(caplog)
    assert line.endswith("session=-")


# --- the content-type check (shield) ---


@pytest.mark.parametrize(
    ("content_type", "status"),
    [
        ("application/json", 200),
        ("Application/JSON", 200),
        ("application/json; charset=utf-8", 200),
        ("  application/json ;charset=utf-8", 200),
        ("application/jsonx", 415),
        ("application/json-seq", 415),
        ("text/plain", 415),
        ("", 415),
    ],
)
def test_the_content_type_is_compared_by_its_media_type(store, content_type, status):
    with client_for(store) as client:
        r = client.post(
            "/api/games", content=b'{"seed": 1}', headers={"content-type": content_type}
        )
    assert r.status_code == status


def test_public_mode_reads_its_own_cookie_name_and_the_trusted_proxy_address(store, caplog):
    settings = {
        "public_origin": "https://gumshoe.example.com",
        "session_secret": SecretStr("s" * 32),
        "trust_proxy": True,
        "ip_requests_per_minute": 1,
    }
    headers = {"cookie": "__Host-gs_session=abcdefghijk.0123", "x-forwarded-for": "203.0.113.9"}
    with capture(caplog), RawClient(app_for(store, **settings)) as client:
        client.get("/api/meta", headers=headers)
        client.get("/api/meta", headers=headers)
    assert lines(caplog) == [
        "refused code=rate_limited route=GET /api/meta ip=203.0.113.9 session=abcdef"
    ]


def test_a_handler_refusal_never_logs_the_query_string_anywhere(store, caplog):
    async def up():
        return True

    app = create_app(
        store,
        make_service=fake_factory(Script(), caps=Caps(games_per_session=1)),
        settings=Settings(_env_file=None),
        personas_up=up,
    )
    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        client.post("/api/games", json={"seed": 1})
        refused = client.post(f"/api/games?text={SECRET_TEXT}", json={"seed": 2})
    assert refused.status_code == 429
    [line] = lines(caplog)
    assert line.startswith("refused code=quota route=POST /api/games ip=")
    server = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    assert server  # the test client's own request log (httpx) is not the server's
    for record in server:  # any server logger, message and arguments alike
        assert SECRET_TEXT not in record.getMessage()


@pytest.mark.parametrize(("trust_proxy", "ip"), [(False, "testclient"), (True, "203.0.113.9")])
def test_a_forwarded_address_is_logged_only_behind_a_trusted_proxy(store, caplog, trust_proxy, ip):
    settings = {"trust_proxy": trust_proxy, "ip_requests_per_minute": 1}
    headers = {"x-forwarded-for": "203.0.113.9"}
    with capture(caplog), RawClient(app_for(store, **settings)) as client:
        client.get("/api/meta", headers=headers)
        client.get("/api/meta", headers=headers)
    assert lines(caplog) == [f"refused code=rate_limited route=GET /api/meta ip={ip} session=-"]
