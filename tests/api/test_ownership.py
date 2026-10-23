from contextlib import contextmanager
from functools import partial

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api import create_app
from gumshoe.api.errors import BAD_SAVE_MESSAGE, UNKNOWN_GAME
from gumshoe.api.saveowners import SaveOwners
from gumshoe.api.session import Sessions
from gumshoe.api.wiring import save_index
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import OWNER, fake_factory, serving

STRANGER = "owner-2"


async def test_the_owner_sees_the_game_and_a_stranger_gets_the_missing_game_error():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        assert (await s.service.state(new.game, owner=OWNER)).brief == new.brief
        with pytest.raises(ToolFailure) as stranger:
            await s.service.state(new.game, owner=STRANGER)
        with pytest.raises(ToolFailure) as missing:
            await s.service.state("nope", owner=OWNER)
    assert (stranger.value.code, stranger.value.message) == (
        missing.value.code,
        missing.value.message,
    )
    assert stranger.value.message == UNKNOWN_GAME


@pytest.mark.parametrize("method", ["state", "turns", "decision_ids", "save_game", "delete_game"])
async def test_every_game_method_refuses_a_stranger(method):
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        call = getattr(s.service, method)
        with pytest.raises(ToolFailure) as caught:
            result = call(new.game, owner=STRANGER)
            if hasattr(result, "__await__"):
                await result
        assert caught.value.code == "unknown_game"
        # the stranger's attempt changed nothing for the owner
        assert (await s.service.state(new.game, owner=OWNER)).outcome == "playing"


async def test_a_stranger_cannot_start_a_turn_or_confirm():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        with pytest.raises(ToolFailure) as turn:
            s.service.start_turn(new.game, "search", owner=STRANGER)
        with pytest.raises(ToolFailure) as confirm:
            s.service.start_confirm(new.game, "p1", "yes", owner=STRANGER)
    assert turn.value.code == "unknown_game"
    assert confirm.value.code == "unknown_game"


async def test_the_list_holds_only_the_callers_games_and_asks_the_engine_about_no_one_else(
    monkeypatch,
):
    async with serving(Script()) as s:
        mine = await s.service.new_game(1, owner=OWNER)
        theirs = await s.service.new_game(2, owner=STRANGER)
        asked: list[str] = []
        real = s.service._deps.client.case_brief

        async def counting(game):
            asked.append(game)
            return await real(game)

        monkeypatch.setattr(s.service._deps.client, "case_brief", counting)
        listed = await s.service.games(owner=OWNER)
    assert [g.game for g in listed] == [mine.game]
    assert asked == [mine.game] and theirs.game not in asked


async def test_a_deleted_game_is_gone_for_its_owner_and_stays_unreachable_for_others():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        await s.service.delete_game(new.game, owner=OWNER)
        for who in (OWNER, STRANGER):
            with pytest.raises(ToolFailure):
                await s.service.state(new.game, owner=who)


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def client_for(store, script=None, saves_dir=None):
    factory = fake_factory(script or Script(), saves_dir=saves_dir)
    return TestClient(create_app(store, make_service=factory))


@contextmanager
def another_browser(client):
    """Use the same server from a browser with its own session (it has made a game of its own)."""
    mine = client.cookies
    client.cookies = type(mine)()
    try:
        assert client.post("/api/games", json={"seed": 99}).status_code == 200
        yield client
    finally:
        client.cookies = mine


@contextmanager
def no_browser_session(client):
    mine = client.cookies
    client.cookies = type(mine)()
    try:
        yield client
    finally:
        client.cookies = mine


def new_game(client, seed=1):
    r = client.post("/api/games", json={"seed": seed})
    assert r.status_code == 200
    return r.json()["game"]


def send(client, method, path, body, game):
    kwargs = {"json": body} if body is not None else {}
    return getattr(client, method)(path.format(g=game), **kwargs)


ROUTES = [
    ("get", "/api/games/{g}", None),
    ("get", "/api/games/{g}/turns", None),
    ("get", "/api/games/{g}/decisions/0123456789abcdef0123456789abcdef", None),
    ("post", "/api/games/{g}/turn", {"text": "hello"}),
    ("post", "/api/games/{g}/confirm", {"pending_id": "p", "answer": "yes"}),
    ("post", "/api/games/{g}/save", None),
    ("delete", "/api/games/{g}", None),
]
MISSING = {"code": "unknown_game", "message": UNKNOWN_GAME}


def test_creating_a_game_issues_the_session_cookie(store):
    with client_for(store) as client:
        r = client.post("/api/games", json={"seed": 1})
    header = r.headers["set-cookie"]
    assert "gs_session=" in header and "HttpOnly" in header and "SameSite=lax" in header


def test_nothing_else_issues_a_cookie(store):
    with client_for(store) as client:
        for path in ("/api/health", "/api/meta", "/api/games", "/api/saves"):
            assert "set-cookie" not in client.get(path).headers
        game = new_game(client)
        assert "set-cookie" not in client.get(f"/api/games/{game}").headers


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_another_sessions_request_reads_exactly_like_a_missing_game(store, method, path, body):
    with client_for(store) as client:
        game = new_game(client)
        with another_browser(client):
            stranger = send(client, method, path, body, game)
            missing = send(client, method, path, body, "0123456789abcdef")
        assert (stranger.status_code, stranger.json()) == (404, MISSING)
        assert (stranger.status_code, stranger.json()) == (missing.status_code, missing.json())
        assert client.get(f"/api/games/{game}").status_code == 200  # the owner is unaffected


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_a_request_with_no_session_reads_the_same(store, method, path, body):
    with client_for(store) as client:
        game = new_game(client)
        with no_browser_session(client):
            r = send(client, method, path, body, game)
        assert (r.status_code, r.json()) == (404, MISSING)


def test_a_stranger_with_a_bad_body_learns_nothing_about_the_game(store):
    with client_for(store) as client:
        game = new_game(client)
        with another_browser(client):
            bad = client.post(f"/api/games/{game}/turn", json={"nope": 1})
            missing = client.post("/api/games/0123456789abcdef/turn", json={"nope": 1})
    assert bad.status_code in (404, 422)
    assert (bad.status_code, bad.json()) == (missing.status_code, missing.json())


def test_the_list_shows_only_my_games_and_nothing_without_a_session(store):
    with client_for(store) as client:
        mine = new_game(client, 1)
        with another_browser(client):
            assert len(client.get("/api/games").json()) == 1  # only its own seed-99 game
            assert client.get("/api/games").json()[0]["game"] != mine
        assert [g["game"] for g in client.get("/api/games").json()] == [mine]
        with no_browser_session(client):
            assert client.get("/api/games").json() == []


def test_a_tampered_cookie_is_no_session(store):
    with client_for(store) as client:
        game = new_game(client)
        client.cookies.set("gs_session", "tampered.value")
        assert client.get(f"/api/games/{game}").status_code == 404
        assert client.get("/api/games").json() == []
        assert client.post("/api/games", json={"seed": 1}).status_code == 200  # a fresh session


def test_a_listing_with_no_cookie_is_an_empty_list_not_an_error(store):
    with client_for(store) as client:
        r = client.get("/api/games")
    assert (r.status_code, r.json()) == (200, [])


def test_a_load_issues_the_session_cookie(store, tmp_path):
    with client_for(store, saves_dir=tmp_path / "saves") as client:
        game = new_game(client)
        saved = client.post(f"/api/games/{game}/save")
        assert saved.status_code == 200
        name = saved.json()["name"]
        with no_browser_session(client):
            r = client.post("/api/games/load", json={"name": name})
    assert r.status_code == 200 and "gs_session=" in r.headers["set-cookie"]


def test_saves_are_listed_and_loadable_only_by_their_owner(store, tmp_path):
    sessions = Sessions(b"k" * 32, secure=False)
    factory = fake_factory(
        Script(),
        saves_dir=tmp_path,
        owners=SaveOwners(tmp_path, sessions),
        list_saves=partial(save_index, tmp_path),
    )
    with TestClient(create_app(store, make_service=factory, sessions=sessions)) as client:
        game = new_game(client)
        name = client.post(f"/api/games/{game}/save").json()["name"]
        assert [s["name"] for s in client.get("/api/saves").json()] == [name]
        with another_browser(client):
            assert client.get("/api/saves").json() == []
            r = client.post("/api/games/load", json={"name": name})
            assert (r.status_code, r.json()) == (
                422,
                {"code": "bad_save", "message": BAD_SAVE_MESSAGE},
            )
        assert client.post("/api/games/load", json={"name": name}).status_code == 200
