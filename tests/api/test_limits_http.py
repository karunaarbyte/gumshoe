import pytest

from gumshoe.api import create_app
from gumshoe.api.ratelimit import TurnGate
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory


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


def test_requests_per_minute_per_ip(store):
    with client_for(store, ip_requests_per_minute=3) as client:
        assert [client.get("/api/meta").status_code for _ in range(3)] == [200, 200, 200]
        r = client.get("/api/meta")
    assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
    assert 1 <= int(r.headers["retry-after"]) <= 60


def test_new_sessions_per_hour_per_ip(store):
    with client_for(store, ip_new_sessions_per_hour=2) as client:
        for _ in range(2):
            client.cookies.clear()
            assert client.post("/api/games", json={"seed": 1}).status_code == 200
        client.cookies.clear()
        r = client.post("/api/games", json={"seed": 1})
        assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
        assert "retry-after" in r.headers


def test_a_returning_session_is_not_a_new_session(store):
    settings = {"ip_new_sessions_per_hour": 1, "session_games_open": 0, "ip_games_open": 0}
    with client_for(store, **settings) as client:
        for seed in (1, 2, 3):
            assert client.post("/api/games", json={"seed": seed}).status_code == 200


def test_a_forged_forwarded_header_does_not_change_the_clients_key_by_default(store):
    with client_for(store, ip_requests_per_minute=2) as client:
        for i in range(2):
            client.get("/api/meta", headers={"x-forwarded-for": f"9.9.9.{i}"})
        r = client.get("/api/meta", headers={"x-forwarded-for": "9.9.9.77"})
        assert r.status_code == 429


def test_with_a_trusted_proxy_the_last_forwarded_entry_is_the_client(store):
    with client_for(store, ip_requests_per_minute=1, trust_proxy=True) as client:
        first = client.get("/api/meta", headers={"x-forwarded-for": "6.6.6.6, 8.8.8.1"})
        second = client.get("/api/meta", headers={"x-forwarded-for": "6.6.6.6, 8.8.8.2"})
        third = client.get("/api/meta", headers={"x-forwarded-for": "1.1.1.1, 8.8.8.1"})
        assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)


def test_a_zero_limit_means_unlimited(store):
    with client_for(store, ip_requests_per_minute=0) as client:
        assert all(client.get("/api/meta").status_code == 200 for _ in range(50))


def test_a_full_gate_is_a_real_429_before_any_streaming(store):
    async def up():
        return True

    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    gate.running = 1  # a turn is running (a test shortcut: the gate only counts)
    app = create_app(
        store,
        make_service=fake_factory(Script(), gate=gate),
        settings=Settings(_env_file=None),
        personas_up=up,
    )
    with TestClient(app) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        r = client.post(f"/api/games/{game}/turn", json={"text": "hello"})
    assert (r.status_code, r.json()["code"], r.headers["retry-after"]) == (429, "busy", "5")
    assert r.headers["content-type"].startswith("application/json")
