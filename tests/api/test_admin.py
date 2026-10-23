import logging
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from gumshoe.api import create_app
from gumshoe.api.ratelimit import Quotas, WindowLimiter
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory
from tests.decider.fakes import FakeClock

TOKEN = "t" * 40
ROUTES = ["/api/stats/decisions", "/api/decisions", "/api/decisions/abc", "/api/admin/usage"]
NOT_FOUND = {"code": "not_found", "message": "Not Found"}


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def client_for(store, clock=None, **settings):
    async def up():
        return True

    app = create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, **settings),
        personas_up=up,
        clock=clock,
    )
    return TestClient(app)


def bearer(token=TOKEN):
    return {"authorization": f"Bearer {token}"}


def shape(response):
    """What a probe can see: status, body and headers (the length differs only with the body)."""
    return response.status_code, response.json(), sorted(response.headers.items())


@pytest.mark.parametrize("path", ROUTES)
def test_with_no_token_configured_the_admin_routes_do_not_exist(store, path):
    with client_for(store) as client:
        unknown = client.get("/api/nothing-here")
        for headers in ({}, bearer()):
            r = client.get(path, headers=headers)
            assert (r.status_code, r.json()) == (404, NOT_FOUND)
            assert shape(r) == shape(unknown)


@pytest.mark.parametrize("path", ROUTES)
def test_a_missing_or_wrong_token_looks_exactly_like_a_missing_route(store, path):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        unknown = client.get("/api/nothing-here")
        for headers in (
            {},
            bearer("x" * 40),
            {"authorization": "Basic abc"},
            {"authorization": "Bearer"},
        ):
            r = client.get(path, headers=headers)
            assert (r.status_code, r.json()) == (unknown.status_code, unknown.json())
            assert (r.status_code, r.json()) == (404, NOT_FOUND)
            assert shape(r) == shape(unknown)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        f"Basic {TOKEN}",
        f"Token {TOKEN}",
        f"Bearer  {TOKEN}",
        f"Bearer {TOKEN} x",
        f"Bearer \t{TOKEN}",
        f"Bearer {TOKEN[:-1]}",
        f"Bearer {TOKEN}x",
        f"Bearer{TOKEN}",
        f"{TOKEN}",
    ],
)
def test_malformed_headers_are_a_plain_404(store, value):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        unknown = client.get("/api/nothing-here")
        r = client.get("/api/decisions", headers={"authorization": value})
    assert shape(r) == shape(unknown)


@pytest.mark.parametrize(
    "path",
    ["/api/decisions?limit=lots", "/api/stats/decisions?since=nope", "/api/decisions/" + "x" * 99],
)
def test_a_bad_query_without_the_token_is_a_404_not_a_422(store, path):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        unknown = client.get("/api/nothing-here")
        assert shape(client.get(path)) == shape(unknown)
        assert client.get(path, headers=bearer()).status_code == 422


@pytest.mark.parametrize("path", ["/api/stats/decisions", "/api/decisions", "/api/admin/usage"])
def test_the_right_token_opens_the_route(store, path):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        assert client.get(path, headers=bearer()).status_code == 200


def test_the_scheme_is_case_insensitive(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        r = client.get("/api/decisions", headers={"authorization": f"bearer {TOKEN}"})
    assert r.status_code == 200


def test_a_non_ascii_header_is_just_a_wrong_token(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        r = client.get("/api/decisions", headers={"authorization": "Bearer é".encode()})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "raw", [b"Bearer \xff\xfe\x80", "Bearer é".encode("latin-1"), b"Bearer \xe2\x80\x8b"]
)
def test_any_non_ascii_bytes_are_a_plain_404_never_a_500(store, raw):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        unknown = client.get("/api/nothing-here")
        r = client.get("/api/decisions", headers={"authorization": raw})
    assert shape(r) == shape(unknown)


def test_too_many_failures_block_even_the_right_token_until_the_window_passes(store):
    clock = FakeClock()
    with client_for(store, admin_token=SecretStr(TOKEN), clock=clock) as client:
        unknown = client.get("/api/nothing-here")
        for _ in range(10):
            assert client.get("/api/decisions", headers=bearer("x" * 40)).status_code == 404
        blocked = client.get("/api/decisions", headers=bearer())
        # not a 429: that would show the route exists
        assert (blocked.status_code, blocked.json()) == (404, NOT_FOUND)
        assert shape(blocked) == shape(unknown)  # no Retry-After, nothing extra
        clock.advance(61)
        assert client.get("/api/decisions", headers=bearer()).status_code == 200


def test_blocked_attempts_do_not_extend_the_block(store):
    clock = FakeClock()
    with client_for(store, admin_token=SecretStr(TOKEN), clock=clock) as client:
        for _ in range(10):
            client.get("/api/decisions", headers=bearer("x" * 40))
        clock.advance(30)
        for _ in range(20):  # while blocked: refused, but not counted
            assert client.get("/api/decisions", headers=bearer("x" * 40)).status_code == 404
        clock.advance(31)
        assert client.get("/api/decisions", headers=bearer()).status_code == 200


def test_nine_failures_do_not_block(store):
    with client_for(store, admin_token=SecretStr(TOKEN), clock=FakeClock()) as client:
        for _ in range(9):
            client.get("/api/decisions", headers=bearer("x" * 40))
        assert client.get("/api/decisions", headers=bearer()).status_code == 200


def test_every_refused_attempt_is_logged_with_the_ip_only(store, caplog):
    with (
        caplog.at_level(logging.INFO, logger="gumshoe.api.admin"),
        client_for(store, admin_token=SecretStr(TOKEN)) as client,
    ):
        client.get("/api/decisions", headers=bearer("x" * 40))
        client.get("/api/decisions")
    lines = [r.getMessage() for r in caplog.records if r.name == "gumshoe.api.admin"]
    assert len(lines) == 2 and all(line.startswith("admin refused ip=") for line in lines)
    assert all(line == "admin refused ip=testclient" for line in lines)
    assert "x" * 40 not in caplog.text and TOKEN not in caplog.text


def test_the_token_is_never_logged_or_returned(store, caplog):
    wrong = "w" * 40
    clock = FakeClock()
    with (
        caplog.at_level(logging.DEBUG),
        client_for(store, admin_token=SecretStr(TOKEN), clock=clock) as client,
    ):
        bodies = [client.get("/api/decisions?secret=q1", headers=bearer()).text]  # success
        for _ in range(10):
            bodies.append(client.get("/api/decisions?secret=q2", headers=bearer(wrong)).text)
        bodies.append(client.get("/api/decisions", headers=bearer()).text)  # blocked
        bodies.append(client.get("/api/admin/usage", headers=bearer()).text)  # blocked
        clock.advance(61)
        bodies.append(client.get("/api/admin/usage", headers=bearer()).text)  # success
        app = client.app
    for text in (caplog.text, *bodies, repr(app.state.__dict__)):
        assert TOKEN not in text and wrong not in text
    admin_lines = [r.getMessage() for r in caplog.records if r.name == "gumshoe.api.admin"]
    assert admin_lines and all("q1" not in x and "q2" not in x for x in admin_lines)
    assert all("Bearer" not in x for x in admin_lines)


def test_the_stored_token_never_shows_in_a_repr():
    from gumshoe.api.admin import admin_token_of

    stored = admin_token_of(TOKEN)
    assert isinstance(stored, bytes) and stored == TOKEN.encode()
    assert TOKEN not in repr(stored) and TOKEN not in str(stored) and TOKEN not in f"{stored}"
    assert admin_token_of("") is None


def test_the_settings_repr_hides_the_token():
    settings = Settings(_env_file=None, admin_token=SecretStr(TOKEN))
    assert TOKEN not in repr(settings) and TOKEN not in str(settings)


def test_admin_routes_set_no_cookie(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        for path in ["/api/stats/decisions", "/api/decisions", "/api/admin/usage"]:
            r = client.get(path, headers=bearer())
            assert r.status_code == 200 and "set-cookie" not in r.headers


def test_the_origin_check_still_applies_to_writes_on_admin_paths(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        no_origin = {**bearer(), "origin": "https://evil.example"}
        r = client.post("/api/decisions", headers=no_origin)
        unknown = client.post("/api/nothing-here", headers=no_origin)
    assert r.status_code == unknown.status_code == 403
    assert r.json() == unknown.json()


def test_a_right_token_is_not_counted_as_a_failure(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        for _ in range(30):
            assert client.get("/api/decisions", headers=bearer()).status_code == 200


def test_the_player_routes_stay_open_without_a_token(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/meta").status_code == 200
        assert client.post("/api/games", json={"seed": 1}).status_code == 200


def test_the_usage_report_shape(store):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    store.add_usage(today, "1.1.1.1", 700)
    store.add_usage(today, "2.2.2.2", 300)
    with client_for(store, admin_token=SecretStr(TOKEN), jev_daily_tokens=5000) as client:
        client.post("/api/games", json={"seed": 1})
        body = client.get("/api/admin/usage", headers=bearer()).json()
    assert set(body) >= {
        "day",
        "jev_tokens_today",
        "jev_daily_cap",
        "jev_ip_daily_cap",
        "mode",
        "games_open",
        "turns_running",
        "queued",
        "shadow_skipped",
        "sessions_seen",
        "saves_held",
        "top_clients",
    }
    assert (body["jev_tokens_today"], body["jev_daily_cap"], body["games_open"]) == (1000, 5000, 1)
    assert body["jev_ip_daily_cap"] == 300_000 and body["sessions_seen"] == 1
    assert body["saves_held"] == 0
    assert {"key": "1.1.1.1", "tokens": 700} in body["top_clients"]


def test_peek_reports_the_wait_and_records_nothing():
    clock = FakeClock()
    limiter = WindowLimiter(2, 60, clock=clock)
    assert limiter.peek("a") is None
    limiter.hit("a")
    assert limiter.peek("a") is None
    limiter.hit("a")
    for _ in range(5):
        assert limiter.peek("a") == 60
    clock.advance(59.5)
    assert limiter.peek("a") == 1
    clock.advance(1)
    assert limiter.peek("a") is None
    assert limiter.hit("a") is None  # the peeks were never counted


def test_peek_with_no_limit_is_always_open():
    assert WindowLimiter(0, 60).peek("a") is None


def test_admin_failures_block_at_ten_per_minute_per_ip():
    clock = FakeClock()
    quotas = Quotas(Settings(_env_file=None), clock=clock)
    for _ in range(9):
        quotas.admin_failed("1.1.1.1")
    assert not quotas.admin_blocked("1.1.1.1")
    quotas.admin_failed("1.1.1.1")
    assert quotas.admin_blocked("1.1.1.1") and not quotas.admin_blocked("2.2.2.2")
    clock.advance(60)
    assert not quotas.admin_blocked("1.1.1.1")


def test_the_failure_table_is_bounded():
    clock = FakeClock()
    quotas = Quotas(Settings(_env_file=None, limiter_max_keys=1000), clock=clock)
    for i in range(5000):
        quotas.admin_failed(f"10.0.{i // 256}.{i % 256}")
    assert len(quotas._admin_failures._hits) <= 1000


# --- other methods and trailing slashes look like an unknown route too ----------------------------

METHODS = ["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def raw(response):
    """Everything a probe sees, byte for byte."""
    return response.status_code, response.content, sorted(response.headers.items())


def block(client):
    for _ in range(10):
        client.get("/api/decisions", headers=bearer("x" * 40))


SCENARIOS = {
    "admin off": ({}, {}, False),
    "no header": ({"admin_token": SecretStr(TOKEN)}, {}, False),
    "wrong token": ({"admin_token": SecretStr(TOKEN)}, bearer("x" * 40), False),
    "blocked ip, right token": ({"admin_token": SecretStr(TOKEN)}, bearer(), True),
}


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("path", ROUTES)
def test_any_method_on_a_gated_path_is_an_unknown_route(store, scenario, method, path):
    settings, headers, blocked = SCENARIOS[scenario]
    with client_for(store, clock=FakeClock(), **settings) as client:
        if blocked:
            block(client)
        unknown = client.request(method, "/api/nothing-here", headers=headers)
        r = client.request(method, path, headers=headers)
    assert raw(r) == raw(unknown)
    assert "allow" not in r.headers and r.status_code == 404


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("method", ["GET", *METHODS])
@pytest.mark.parametrize("path", ROUTES)
def test_a_trailing_slash_on_a_gated_path_is_an_unknown_route(store, scenario, method, path):
    settings, headers, blocked = SCENARIOS[scenario]
    with client_for(store, clock=FakeClock(), **settings) as client:
        if blocked:
            block(client)
        unknown = client.request(method, "/api/nothing-here/", headers=headers)
        r = client.request(method, path + "/", headers=headers, follow_redirects=False)
    assert raw(r) == raw(unknown)
    assert "location" not in r.headers and r.status_code == 404


def test_a_wrong_token_on_another_method_counts_and_is_logged(store, caplog):
    with (
        caplog.at_level(logging.INFO, logger="gumshoe.api.admin"),
        client_for(store, admin_token=SecretStr(TOKEN), clock=FakeClock()) as client,
    ):
        for _ in range(10):
            assert client.post("/api/decisions", headers=bearer("x" * 40)).status_code == 404
        assert client.get("/api/decisions", headers=bearer()).status_code == 404  # blocked
    lines = [r.getMessage() for r in caplog.records if r.name == "gumshoe.api.admin"]
    assert lines == ["admin refused ip=testclient"] * 11
    assert TOKEN not in caplog.text and "x" * 40 not in caplog.text


def test_the_right_token_still_opens_get_and_a_wrong_method_may_say_so(store):
    with client_for(store, admin_token=SecretStr(TOKEN)) as client:
        assert client.get("/api/admin/usage", headers=bearer()).status_code == 200
        assert client.post("/api/admin/usage", headers=bearer()).status_code == 405


def test_a_cors_preflight_may_ask_to_send_the_token(store):
    preflight = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    with client_for(store, admin_token=SecretStr(TOKEN), cors_origins="http://localhost:5173") as c:
        listed = c.options(
            "/api/decisions", headers={"Origin": "http://localhost:5173", **preflight}
        )
        other = c.options("/api/decisions", headers={"Origin": "http://evil.test", **preflight})
    assert listed.status_code == 200
    assert "authorization" in listed.headers["access-control-allow-headers"].lower()
    assert listed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert other.status_code == 400 and "access-control-allow-origin" not in other.headers
