import pytest
from starlette.testclient import TestClient

from gumshoe.agent.events import EVENT_ADAPTER
from gumshoe.api import create_app
from gumshoe.api.errors import status_for
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.helpers import fake_factory, parse_sse


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def client_for(store, script, **kw):
    return TestClient(create_app(store, make_service=fake_factory(script, **kw)))


def new_game(client, seed=1):
    response = client.post("/api/games", json={"seed": seed})
    assert response.status_code == 200
    return response.json()


def test_create_a_game_returns_its_id_and_brief(store):
    with client_for(store, Script()) as client:
        body = new_game(client)
    assert set(body) == {"game", "brief"} and body["brief"]["status"] == "playing"
    assert body["brief"]["locations"] and "truth" not in str(body)


def test_get_a_game_returns_brief_and_notebook(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        body = client.get(f"/api/games/{game}").json()
    assert set(body) == {"brief", "notebook"}


def test_a_turn_streams_sse_that_parses_back_to_the_events(store):
    script = Script().understand(intent="search", target="place_1")
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        with client.stream("POST", f"/api/games/{game}/turn", json={"text": "search"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(r.iter_text())
    pairs = parse_sse(body)
    assert [name for name, _ in pairs] == ["intent", "tool_call", "tool_result", "done"]
    for name, data in pairs:
        assert EVENT_ADAPTER.validate_python(data).kind == name


def test_turn_on_an_unknown_game_is_404_before_streaming(store):
    with client_for(store, Script()) as client:
        response = client.post("/api/games/nope/turn", json={"text": "hi"})
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_game"
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("text", ["", "x" * 1001])
def test_turn_text_must_be_1_to_1000_characters(store, text):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        response = client.post(f"/api/games/{game}/turn", json={"text": text})
    assert response.status_code == 422 and "detail" in response.json()


def test_a_1000_character_turn_is_accepted(store):
    script = Script().understand(intent="notebook")
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        with client.stream("POST", f"/api/games/{game}/turn", json={"text": "x" * 1000}) as r:
            assert r.status_code == 200
            "".join(r.iter_text())


@pytest.mark.parametrize(
    "body", [{}, {"seed": "1"}, {"seed": 1.5}, {"seed": True}, {"seed": 1, "extra": 1}]
)
def test_creating_a_game_validates_the_body(store, body):
    with client_for(store, Script()) as client:
        assert client.post("/api/games", json=body).status_code == 422


def test_a_bad_seed_or_preset_is_422_with_code_and_message(store):
    with client_for(store, Script()) as client:
        seed = client.post("/api/games", json={"seed": -1})
        preset = client.post("/api/games", json={"seed": 1, "preset": "nonsense"})
    for response in (seed, preset):
        assert response.status_code == 422
        assert set(response.json()) == {"code", "message"}
        assert response.json()["code"] == "bad_argument"


def test_save_then_load_makes_a_new_game(store, tmp_path):
    with client_for(store, Script(), saves_dir=tmp_path / "saves") as client:
        game = new_game(client)["game"]
        saved = client.post(f"/api/games/{game}/save")
        assert saved.status_code == 200
        loaded = client.post("/api/games/load", json={"name": saved.json()["name"]})
        assert loaded.status_code == 200 and loaded.json()["game"] != game


def test_loading_a_missing_save_is_422(store, tmp_path):
    with client_for(store, Script(), saves_dir=tmp_path / "saves") as client:
        response = client.post("/api/games/load", json={"name": "0123456789abcdef"})
    assert response.status_code == 422 and response.json()["code"] == "bad_save"


def test_loading_a_malformed_name_is_422(store, tmp_path):
    with client_for(store, Script(), saves_dir=tmp_path / "saves") as client:
        response = client.post("/api/games/load", json={"name": "../etc/passwd"})
    assert response.status_code == 422 and response.json()["code"] == "bad_argument"


def test_save_of_an_unknown_game_is_404(store):
    with client_for(store, Script()) as client:
        assert client.post("/api/games/nope/save").status_code == 404


def test_delete_frees_the_game(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        assert client.delete(f"/api/games/{game}").status_code == 204
        assert client.get(f"/api/games/{game}").status_code == 404
        assert client.delete(f"/api/games/{game}").status_code == 404


def test_the_open_game_cap_answers_429_and_delete_lifts_it(store, monkeypatch):
    # the host reads its module constant at call time; 1000 real games would take ~12 s
    monkeypatch.setattr("gumshoe.mcp_server.host.MAX_GAMES", 3)
    with client_for(store, Script()) as client:
        ids = [new_game(client, seed=i)["game"] for i in range(1, 4)]
        full = client.post("/api/games", json={"seed": 99})
        assert full.status_code == 429 and full.json()["code"] == "too_many_games"
        assert client.delete(f"/api/games/{ids[0]}").status_code == 204
        assert client.post("/api/games", json={"seed": 99}).status_code == 200


def test_the_stats_endpoints_still_work_beside_the_games(store):
    with client_for(store, Script()) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/decisions").json() == []


def test_a_save_write_failure_is_500(store):
    from contextlib import asynccontextmanager

    from gumshoe.agent import ToolFailure
    from gumshoe.api.service import AgentService
    from tests.api.helpers import serving

    class Failing(AgentService):
        async def save_game(self, game):
            raise ToolFailure("bad_save", "could not write the save")

    @asynccontextmanager
    async def factory(_store):
        async with serving(Script()) as served:
            yield Failing(served.service._deps)

    with TestClient(create_app(store, make_service=factory)) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        response = client.post(f"/api/games/{game}/save")
    assert response.status_code == 500 and response.json()["code"] == "bad_save"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("unknown_game", 404),
        ("bad_argument", 422),
        ("unknown_handle", 422),
        ("bad_save", 422),
        ("internal", 500),
        ("too_many_games", 429),
        ("game_over", 409),
        ("not_over", 409),
        ("state_mismatch", 409),
        ("a_code_added_later", 409),
    ],
)
def test_every_tool_failure_code_has_its_status(code, status):
    assert status_for(code) == status


def test_an_unexpected_error_is_a_500_with_code_and_message_only(store):
    from contextlib import asynccontextmanager

    from gumshoe.api.service import AgentService
    from tests.api.helpers import serving

    class Broken(AgentService):
        async def state(self, game):
            raise RuntimeError("secret detail")

    @asynccontextmanager
    async def factory(_store):
        async with serving(Script()) as served:
            yield Broken(served.service._deps)

    app = create_app(store, make_service=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/games/x")
    assert response.status_code == 500
    assert response.json() == {"code": "internal", "message": "something went wrong"}
