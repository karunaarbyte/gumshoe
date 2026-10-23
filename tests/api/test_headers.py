import asyncio

import pytest
from pydantic import SecretStr, ValidationError

from gumshoe.api import create_app
from gumshoe.api.headers import SecurityHeaders
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
)
PUBLIC = "https://gumshoe.example.com"
PUBLIC_MODE = {"public_origin": PUBLIC, "session_secret": SecretStr("s" * 32)}
DOCS = ("/docs", "/redoc", "/openapi.json")


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def client_for(store, **settings):
    async def up():
        return True

    app = create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, **settings),
        personas_up=up,
    )
    return TestClient(app)


def assert_secured(r):
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY"


def shape(response):
    return response.status_code, response.json(), sorted(response.headers.items())


def test_every_response_carries_the_security_headers(store):
    with client_for(store) as client:
        for r in (
            client.get("/api/meta"),
            client.get("/api/nothing"),
            client.post("/api/games", json={"seed": 1}),
        ):
            assert_secured(r)


def test_refusals_from_the_other_middleware_carry_them_too(store):
    with client_for(store, ip_requests_per_minute=1, max_body_bytes=1024) as client:
        json_type = {"content-type": "application/json"}
        too_big = client.post("/api/games", content=b"x" * 2048, headers=json_type)
        assert too_big.status_code == 413
        assert_secured(too_big)
        limited = client.get("/api/meta")
        assert limited.status_code == 429
        assert_secured(limited)
    with client_for(store, **PUBLIC_MODE) as client:
        refused = client.post("/api/games", json={"seed": 1}, headers={"origin": "https://evil"})
        assert refused.status_code == 403
        assert_secured(refused)


def test_api_responses_are_not_cached_unless_they_say_otherwise(store):
    with client_for(store) as client:
        assert client.get("/api/meta").headers["cache-control"] == "no-store"
        assert client.get("/api/nothing").headers["cache-control"] == "no-store"


def test_the_event_stream_keeps_its_own_cache_headers(store):
    with client_for(store) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        with client.stream("POST", f"/api/games/{game}/turn", json={"text": "hello"}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-cache"
            assert r.headers["x-accel-buffering"] == "no"
            assert_secured(r)
            r.read()


def test_hsts_only_in_public_mode(store):
    with client_for(store) as client:
        assert "strict-transport-security" not in client.get("/api/meta").headers
    with client_for(store, **PUBLIC_MODE) as client:
        hsts = client.get("/api/meta").headers["strict-transport-security"]
        assert hsts == "max-age=31536000"


def test_the_docs_are_off_by_default(store):
    with client_for(store) as client:
        for path in DOCS:
            assert client.get(path).status_code == 404


@pytest.mark.parametrize("settings", [{}, PUBLIC_MODE], ids=["local", "public"])
def test_a_disabled_docs_route_looks_exactly_like_an_unknown_route(store, settings):
    with client_for(store, **settings) as client:
        unknown = client.get("/api/nothing-here")
        for path in DOCS:
            assert shape(client.get(path)) == shape(unknown)


def test_the_docs_can_be_turned_on_locally(store):
    with client_for(store, api_docs=True) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200


def test_the_docs_cannot_be_turned_on_in_public_mode():
    with pytest.raises(ValidationError, match="API_DOCS"):
        Settings(_env_file=None, api_docs=True, **PUBLIC_MODE)


def test_the_stream_is_passed_on_chunk_by_chunk_not_buffered():
    seen: list[dict] = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"one", "more_body": True})
        assert seen[-1]["body"] == b"one"  # already out before the next chunk is made
        await send({"type": "http.response.body", "body": b"two", "more_body": False})

    async def send(message):
        seen.append(message)

    scope = {"type": "http", "path": "/api/x", "headers": []}
    asyncio.run(SecurityHeaders(inner)(scope, None, send))
    assert [m["type"] for m in seen] == ["http.response.start", *["http.response.body"] * 2]
    assert [m.get("body") for m in seen[1:]] == [b"one", b"two"]


def test_other_scopes_pass_through_untouched():
    calls: list[tuple] = []

    async def inner(scope, receive, send):
        calls.append((scope, receive, send))

    async def receive():
        return {}

    async def send(message):
        pass

    scope = {"type": "lifespan"}
    asyncio.run(SecurityHeaders(inner)(scope, receive, send))
    assert calls == [(scope, receive, send)]


def test_mixed_case_headers_from_downstream_are_neither_duplicated_nor_kept():
    seen: list[dict] = []

    async def inner(scope, receive, send):
        headers = [
            (b"Cache-Control", b"max-age=60"),
            (b"Content-Security-Policy", b"default-src *"),
            (b"X-Content-Type-Options", b"sniff-away"),
            (b"Content-Type", b"text/plain"),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def send(message):
        seen.append(message)

    scope = {"type": "http", "path": "/api/x", "headers": []}
    asyncio.run(SecurityHeaders(inner)(scope, None, send))
    raw = seen[0]["headers"]
    names = [name.lower() for name, _ in raw]
    assert len(names) == len(set(names))  # no header twice, whatever its case
    values = {name.lower(): value for name, value in raw}
    assert values[b"cache-control"] == b"max-age=60"  # downstream caching is kept
    assert values[b"content-security-policy"] == CSP.encode()
    assert values[b"x-content-type-options"] == b"nosniff"
    assert values[b"content-type"] == b"text/plain"


def _client_with_a_failing_route(store, **settings):
    from starlette.routing import Route

    async def up():
        return True

    app = create_app(
        store,
        make_service=fake_factory(Script()),
        settings=Settings(_env_file=None, **settings),
        personas_up=up,
    )

    def boom(request):
        raise RuntimeError("an unexpected failure")

    app.router.routes.insert(0, Route("/api/boom", boom))
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("public", [False, True])
def test_an_unexpected_500_carries_the_security_headers(store, public):
    settings = PUBLIC_MODE if public else {}
    with _client_with_a_failing_route(store, **settings) as client:
        r = client.get("/api/boom", headers={"origin": PUBLIC} if public else {})
    assert (r.status_code, r.json()["code"]) == (500, "internal")
    assert "unexpected failure" not in r.text
    assert_secured(r)
    assert r.headers["cache-control"] == "no-store"
    assert ("strict-transport-security" in r.headers) is public
    if public:
        assert r.headers["strict-transport-security"] == "max-age=31536000"
