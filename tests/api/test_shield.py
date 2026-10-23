import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient as RawClient

from gumshoe.api import create_app
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.helpers import fake_factory

PUBLIC = "https://gumshoe.example.com"


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


def public_app(store, **extra):
    return app_for(store, public_origin=PUBLIC, session_secret=SecretStr("s" * 32), **extra)


def post(client, **headers):
    return client.post("/api/games", json={"seed": 1}, headers=headers)


def test_a_write_without_an_origin_is_refused(store):
    with RawClient(app_for(store)) as client:
        r = post(client)
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")


LOCAL = "http://localhost"


def test_a_write_from_the_sites_own_origin_passes_in_local_mode(store):
    with RawClient(app_for(store), base_url=LOCAL) as client:
        assert post(client, origin=LOCAL).status_code == 200


@pytest.mark.parametrize(
    "base",
    ["http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:8000", "http://LOCALHOST"],
)
def test_a_loopback_host_is_its_own_origin_in_local_mode(store, base):
    # the Vite proxy (changeOrigin off) and a direct visit to the API both look like this
    with RawClient(app_for(store), base_url=base) as client:
        assert post(client, origin=base.lower()).status_code == 200


@pytest.mark.parametrize(
    "base", ["http://testserver", "http://evil.example", "http://0.0.0.0:8000", "http://10.0.0.5"]
)
def test_a_rebound_host_is_not_its_own_origin(store, base):
    # DNS rebinding: a hostile name pointed at this machine sends Origin == its own Host
    with RawClient(app_for(store), base_url=base) as client:
        r = post(client, origin=base)
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")


def test_a_rebound_host_listed_in_cors_origins_is_allowed(store):
    app = app_for(store, cors_origins="http://gumshoe.lan:8000")
    with RawClient(app, base_url="http://gumshoe.lan:8000") as client:
        assert post(client, origin="http://gumshoe.lan:8000").status_code == 200


def test_a_foreign_origin_is_refused(store):
    with RawClient(app_for(store)) as client:
        assert post(client, origin="http://evil.example").status_code == 403
        assert post(client, origin="null").status_code == 403


def test_an_origin_that_only_starts_like_the_allowed_one_is_refused(store):
    with RawClient(public_app(store), base_url=PUBLIC) as client:
        assert post(client, origin=PUBLIC + ".evil.com").status_code == 403
        assert post(client, origin=PUBLIC + "@evil.com").status_code == 403
        assert post(client, origin=PUBLIC).status_code == 200


def test_the_referer_stands_in_when_there_is_no_origin(store):
    with RawClient(app_for(store), base_url=LOCAL) as client:
        assert post(client, referer=LOCAL + "/some/page").status_code == 200
        assert post(client, referer="http://evil.example/page").status_code == 403


def test_public_mode_does_not_trust_the_request_host(store):
    with RawClient(public_app(store)) as client:  # Host is testserver, not the public origin
        assert post(client, origin="http://testserver").status_code == 403
    with RawClient(public_app(store), base_url="http://localhost") as client:
        assert post(client, origin="http://localhost").status_code == 403  # not even loopback


def test_a_cors_origin_is_allowed(store):
    app = app_for(store, cors_origins="http://localhost:5173")
    with RawClient(app) as client:
        assert post(client, origin="http://localhost:5173").status_code == 200


def test_reads_never_need_an_origin(store):
    with RawClient(app_for(store)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/meta").status_code == 200


def test_delete_needs_an_origin_too(store):
    with RawClient(app_for(store)) as client:
        assert client.delete("/api/games/whatever").status_code == 403


def test_a_body_that_is_not_json_is_refused_even_from_the_right_origin(store):
    with RawClient(app_for(store), base_url=LOCAL) as client:
        r = client.post(
            "/api/games",
            content=b'{"seed": 1}',
            headers={"origin": LOCAL, "content-type": "text/plain"},
        )
    assert (r.status_code, r.json()["code"]) == (415, "bad_request")


def test_a_write_with_no_body_needs_no_content_type(store):
    with RawClient(app_for(store), base_url=LOCAL) as client:
        created = post(client, origin=LOCAL).json()
        r = client.post(f"/api/games/{created['game']}/save", headers={"origin": LOCAL})
    assert r.status_code != 403 and r.status_code != 415


def test_the_refusal_has_the_standard_error_shape_and_leaks_nothing(store):
    with RawClient(app_for(store)) as client:
        body = post(client, origin="http://evil.example").json()
    assert set(body) == {"code", "message"} and "evil" not in body["message"]


def test_a_mixed_case_public_origin_still_matches_the_browsers_lowercase_origin(store):
    app = app_for(
        store, public_origin="https://Gumshoe.Example.COM", session_secret=SecretStr("s" * 32)
    )
    with RawClient(app, base_url=PUBLIC) as client:
        assert post(client, origin=PUBLIC).status_code == 200
        assert post(client, origin=PUBLIC + ".evil.com").status_code == 403
