import asyncio
from contextlib import asynccontextmanager

import pytest
from pydantic import SecretStr

from gumshoe.agent.events import EVENT_ADAPTER, Done
from gumshoe.api import create_app
from gumshoe.api.errors import status_for
from gumshoe.api.games import PING, sse, with_pings
from gumshoe.config import Settings
from gumshoe.mcp_server import GameHost
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script, ScriptedDecider
from tests.api.client import TestClient
from tests.api.helpers import fake_factory, parse_sse, serving


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
    assert set(body) == {"game", "brief", "preset"} and body["brief"]["status"] == "playing"
    assert body["preset"] == "standard" and "seed" not in body
    assert body["brief"]["locations"] and "truth" not in str(body)


def test_get_a_game_returns_brief_and_notebook(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        body = client.get(f"/api/games/{game}").json()
    assert set(body) == {"brief", "notebook", "outcome", "pending", "reveal", "preset"}
    assert (body["outcome"], body["pending"], body["reveal"]) == ("playing", None, None)


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
    assert response.status_code == 422 and set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "bad_request"


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
        assert loaded.json()["preset"] is None  # a save does not say


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
    # the test helpers build GameHost() with its default cap; 1000 real games would take ~12 s
    monkeypatch.setattr(GameHost.__init__, "__kwdefaults__", {"max_games": 3})
    with client_for(store, Script()) as client:
        ids = [new_game(client, seed=i)["game"] for i in range(1, 4)]
        full = client.post("/api/games", json={"seed": 99})
        assert full.status_code == 429 and full.json()["code"] == "too_many_games"
        assert client.delete(f"/api/games/{ids[0]}").status_code == 204
        assert client.post("/api/games", json={"seed": 99}).status_code == 200


def test_the_stats_endpoints_still_work_beside_the_games(store):
    settings = Settings(_env_file=None, admin_token=SecretStr("t" * 40))
    app = create_app(store, make_service=fake_factory(Script()), settings=settings)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert (health["status"], health["game"]) == ("ok", "on")
        admin = {"authorization": "Bearer " + "t" * 40}
        assert client.get("/api/decisions", headers=admin).json() == []


def test_a_save_write_failure_is_500(store):
    from contextlib import asynccontextmanager

    from gumshoe.agent import ToolFailure
    from gumshoe.api.service import AgentService
    from tests.api.helpers import serving

    class Failing(AgentService):
        async def save_game(self, game, *, owner, ip=""):
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
        async def state(self, game, *, owner):
            raise RuntimeError("secret detail")

    @asynccontextmanager
    async def factory(_store):
        async with serving(Script()) as served:
            yield Broken(served.service._deps)

    app = create_app(store, make_service=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]  # makes a session
        response = client.get(f"/api/games/{game}")
    assert response.status_code == 500
    assert response.json() == {"code": "internal", "message": "something went wrong"}


def test_a_turn_while_another_runs_is_409_before_streaming(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        client.app.state.service._slots[game].busy = True  # as if a turn were running
        response = client.post(f"/api/games/{game}/turn", json={"text": "hi"})
    assert response.status_code == 409
    assert response.json()["code"] == "turn_in_progress"
    assert response.headers["content-type"].startswith("application/json")


def test_a_typed_yes_carrying_the_confirmations_id_runs_it(store):
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.95)
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        first = parse_sse(client.post(f"/api/games/{game}/turn", json={"text": "I quit"}).text)
        [confirm] = [data for name, data in first if name == "confirm"]
        body = {"text": "yes", "pending_id": confirm["pending_id"]}
        second = parse_sse(client.post(f"/api/games/{game}/turn", json=body).text)
    assert [name for name, _ in second][-2:] == ["game_over", "done"]


def test_an_empty_pending_id_is_refused(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        body = {"text": "yes", "pending_id": ""}
        assert client.post(f"/api/games/{game}/turn", json=body).status_code == 422


# --- keep-alive pings ----------------------------------------------------------------------------


async def test_a_quiet_stream_gets_pings_between_its_events():
    async def slow():
        await asyncio.sleep(0.05)
        yield Done()

    chunks = [chunk async for chunk in with_pings(slow(), 0.01)]
    assert chunks[0] == PING and chunks[-1] == sse(Done())
    assert set(chunks[:-1]) == {PING}


async def test_leaving_a_pinged_stream_closes_the_events_behind_it():
    closed = asyncio.Event()

    async def endless():
        try:
            await asyncio.sleep(10)
            yield Done()
        finally:
            closed.set()

    stream = with_pings(endless(), 0.01)
    assert await anext(stream) == PING
    await stream.aclose()
    assert closed.is_set()  # so the service learns its reader is gone


def test_a_slow_turn_streams_pings_that_parse_sse_skips(store, monkeypatch):
    monkeypatch.setattr("gumshoe.api.games.PING_INTERVAL_S", 0.01)

    class Slow(ScriptedDecider):
        async def decide(self, state, questions, *, node="adhoc", decision_id=None):
            await asyncio.sleep(0.1)
            return await super().decide(state, questions, node=node, decision_id=decision_id)

    script = Script().understand(intent="notebook")

    @asynccontextmanager
    async def factory(_store):
        async with serving(script, decider=Slow(script)) as served:
            yield served.service

    with TestClient(create_app(store, make_service=factory)) as client:
        game = new_game(client)["game"]
        body = client.post(f"/api/games/{game}/turn", json={"text": "notes"}).text
    assert body.startswith(": ping\n\n")
    assert [name for name, _ in parse_sse(body)] == ["intent", "tool_call", "tool_result", "done"]


async def test_leaving_right_after_an_event_closes_the_events_behind_it():
    closed = asyncio.Event()

    async def two():
        try:
            yield Done()
            await asyncio.sleep(10)
            yield Done()
        finally:
            closed.set()

    stream = with_pings(two(), 1.0)
    assert await anext(stream) == sse(Done())  # suspended at `yield sse(event)`
    await stream.aclose()
    assert closed.is_set()  # closed explicitly, not by the garbage collector


async def test_closing_before_the_first_read_still_closes_the_events():
    class Events:
        closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            self.closed = True

    events = Events()
    stream = with_pings(events, 1.0)
    await stream.aclose()
    assert events.closed


# --- the confirm button and the transcript -------------------------------------------------------


def test_the_confirm_endpoint_streams_the_same_events_as_a_turn(store):
    script = Script().understand(intent="give_up")
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        first = parse_sse(client.post(f"/api/games/{game}/turn", json={"text": "I quit"}).text)
        [confirm] = [data for name, data in first if name == "confirm"]
        body = {"pending_id": confirm["pending_id"], "answer": "yes"}
        with client.stream("POST", f"/api/games/{game}/confirm", json=body) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            pairs = parse_sse("".join(r.iter_text()))
    assert [name for name, _ in pairs] == ["tool_call", "tool_result", "game_over", "done"]


def test_a_confirm_for_nothing_waiting_is_409_and_an_unknown_game_404(store):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        body = {"pending_id": "0" * 32, "answer": "yes"}
        stale = client.post(f"/api/games/{game}/confirm", json=body)
        unknown = client.post("/api/games/nope/confirm", json=body)
    assert stale.status_code == 409 and stale.json()["code"] == "no_such_pending"
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    "body", [{"pending_id": "p", "answer": "maybe"}, {"answer": "yes"}, {"pending_id": "p"}]
)
def test_a_confirm_body_is_validated(store, body):
    with client_for(store, Script()) as client:
        game = new_game(client)["game"]
        assert client.post(f"/api/games/{game}/confirm", json=body).status_code == 422


def test_the_transcript_endpoint_returns_every_turn(store):
    script = Script().understand(intent="notebook")
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        client.post(f"/api/games/{game}/turn", json={"text": "notes"})
        turns = client.get(f"/api/games/{game}/turns").json()
        missing = client.get("/api/games/nope/turns")
    [turn] = turns
    assert set(turn) == {"turn_id", "kind", "text", "ts", "events", "complete"}
    assert turn["text"] == "notes" and turn["events"][-1]["kind"] == "done"
    assert missing.status_code == 404


# --- the game as a reloaded page sees it ---------------------------------------------------------


def test_a_reloaded_page_gets_the_waiting_confirmation_back(store):
    script = Script().understand(intent="give_up")
    with client_for(store, script) as client:
        game = new_game(client)["game"]
        first = parse_sse(client.post(f"/api/games/{game}/turn", json={"text": "I quit"}).text)
        [confirm] = [data for name, data in first if name == "confirm"]
        body = client.get(f"/api/games/{game}").json()
    assert body["pending"] == {
        "pending_id": confirm["pending_id"],
        "kind": "give_up",
        "text": confirm["text"],
        "warnings": [],
    }


def test_the_open_games_are_listed(store):
    with client_for(store, Script()) as client:
        a = new_game(client)["game"]
        b = client.post("/api/games", json={"seed": 2, "preset": "short"}).json()["game"]
        listed = client.get("/api/games").json()
    assert [(g["game"], g["preset"], g["outcome"]) for g in listed] == [
        (a, "standard", "playing"),
        (b, "short", "playing"),
    ]
    assert all(g["attempts_left"] == 3 and g["turn_running"] is False for g in listed)


def test_saves_answers_a_list(store):
    with client_for(store, Script()) as client:
        response = client.get("/api/saves")
    assert response.status_code == 200 and response.json() == []
