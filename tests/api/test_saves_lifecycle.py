import asyncio
from functools import partial

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api import create_app
from gumshoe.api.errors import BAD_SAVE_MESSAGE, ApiError
from gumshoe.api.saveowners import SaveOwners
from gumshoe.api.service import Caps
from gumshoe.api.session import Sessions
from gumshoe.api.wiring import save_index
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import OWNER, fake_factory, serving


def wired(tmp_path, **kw):
    sessions = Sessions(b"k" * 32, secure=False)
    owners = SaveOwners(tmp_path, sessions)
    return (
        sessions,
        owners,
        dict(saves_dir=tmp_path, owners=owners, list_saves=partial(save_index, tmp_path), **kw),
    )


async def test_saves_per_session_are_capped_and_a_refused_save_writes_nothing(tmp_path):
    _, _, kw = wired(tmp_path, caps=Caps(saves_per_session=2))
    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await s.service.save_game(g.game, owner=OWNER)
        await s.service.save_game(g.game, owner=OWNER)
        with pytest.raises(ApiError) as caught:
            await s.service.save_game(g.game, owner=OWNER)
        assert (caught.value.status, caught.value.code) == (429, "quota")
        assert len(list(tmp_path.glob("*.json"))) == 2
        other = await s.service.new_game(2, owner="bob")
        await s.service.save_game(other.game, owner="bob")


async def test_saves_per_ip_are_capped_across_sessions(tmp_path):
    _, _, kw = wired(tmp_path, caps=Caps(saves_per_ip=2))
    async with serving(Script(), **kw) as s:
        for owner in ("a", "b"):
            g = await s.service.new_game(1, owner=owner)
            await s.service.save_game(g.game, owner=owner, ip="1.1.1.1")
        g = await s.service.new_game(1, owner="c")
        with pytest.raises(ApiError):
            await s.service.save_game(g.game, owner="c", ip="1.1.1.1")
        await s.service.save_game(g.game, owner="c", ip="2.2.2.2")


async def test_saves_made_at_the_same_moment_cannot_slip_under_the_cap(tmp_path):
    _, _, kw = wired(tmp_path, caps=Caps(saves_per_session=2))
    async with serving(Script(), **kw) as s:
        games = [await s.service.new_game(i, owner=OWNER) for i in range(4)]
        results = await asyncio.gather(
            *(s.service.save_game(g.game, owner=OWNER) for g in games), return_exceptions=True
        )
        assert sum(isinstance(r, ApiError) for r in results) == 2
        assert len(list(tmp_path.glob("*.json"))) == 2


async def test_the_owner_can_delete_a_save_and_it_frees_the_cap(tmp_path):
    _, _, kw = wired(tmp_path, caps=Caps(saves_per_session=1))
    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        saved = await s.service.save_game(g.game, owner=OWNER)
        await s.service.delete_save(saved.name, owner=OWNER)
        assert list(tmp_path.iterdir()) == []
        await s.service.save_game(g.game, owner=OWNER)


async def test_deleting_someone_elses_save_does_nothing_and_reads_like_a_missing_one(tmp_path):
    _, _, kw = wired(tmp_path)
    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        saved = await s.service.save_game(g.game, owner=OWNER)
        with pytest.raises(ToolFailure) as stranger:
            await s.service.delete_save(saved.name, owner="bob")
        with pytest.raises(ToolFailure) as missing:
            await s.service.delete_save("0123456789abcdef", owner="bob")
        assert (stranger.value.code, stranger.value.message) == ("bad_save", BAD_SAVE_MESSAGE)
        assert (stranger.value.code, stranger.value.message) == (
            missing.value.code,
            missing.value.message,
        )
        assert (tmp_path / f"{saved.name}.json").exists()


async def test_purge_saves_deletes_old_ones(tmp_path):
    import os
    import time

    _, _, kw = wired(tmp_path)
    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        old = await s.service.save_game(g.game, owner=OWNER)
        new = await s.service.save_game(g.game, owner=OWNER)
        long_ago = time.time() - 40 * 86400
        os.utime(tmp_path / f"{old.name}.json", (long_ago, long_ago))
        assert await s.service.purge_saves(30 * 86400.0) == 1
        assert [x.name for x in await s.service.saves(owner=OWNER)] == [new.name]


async def test_purge_saves_with_no_retention_keeps_everything(tmp_path):
    _, _, kw = wired(tmp_path)
    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await s.service.save_game(g.game, owner=OWNER)
        assert await s.service.purge_saves(0) == 0
        assert len(list(tmp_path.glob("*.json"))) == 1


async def test_a_save_that_cannot_be_claimed_is_removed_and_fails_without_detail(
    tmp_path, monkeypatch
):
    _, owners, kw = wired(tmp_path, caps=Caps(saves_per_ip=1))

    def broken_claim(name, owner, ip=""):
        raise OSError(f"disk full writing {tmp_path}/{name}.owner")

    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        monkeypatch.setattr(owners, "claim", broken_claim)
        with pytest.raises(ApiError) as caught:
            await s.service.save_game(g.game, owner=OWNER, ip="1.1.1.1")
        assert caught.value.status == 500
        assert str(tmp_path) not in caught.value.message
        assert list(tmp_path.iterdir()) == []  # no unowned save left behind
        monkeypatch.undo()
        await s.service.save_game(g.game, owner=OWNER, ip="1.1.1.1")


async def test_a_save_cancelled_before_it_is_claimed_is_removed(tmp_path, monkeypatch):
    import threading

    _, owners, kw = wired(tmp_path)
    started, release = threading.Event(), threading.Event()

    def slow_claim(name, owner, ip=""):
        started.set()
        release.wait(5)  # the request is cancelled while the claim is under way

    async with serving(Script(), **kw) as s:
        g = await s.service.new_game(1, owner=OWNER)
        monkeypatch.setattr(owners, "claim", slow_claim)
        task = asyncio.create_task(s.service.save_game(g.game, owner=OWNER))
        assert await asyncio.to_thread(started.wait, 5)
        assert len(list(tmp_path.glob("*.json"))) == 1  # the host wrote it
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        release.set()
        assert list(tmp_path.iterdir()) == []  # no unclaimed save left behind


def test_the_save_cap_message_says_nothing_of_other_saves(tmp_path):
    sessions, _, kw = wired(tmp_path, caps=Caps(saves_per_session=1))
    store = SqliteStatsStore(tmp_path / "d.db")
    app = create_app(store, make_service=fake_factory(Script(), **kw), sessions=sessions)
    with TestClient(app) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        assert client.post(f"/api/games/{game}/save").status_code == 200
        refused = client.post(f"/api/games/{game}/save")
        assert (refused.status_code, refused.json()["code"]) == (429, "quota")
        assert not any(c.isdigit() for c in refused.json()["message"])  # no names, no counts


def test_the_delete_route(tmp_path):
    sessions, owners, kw = wired(tmp_path)
    store = SqliteStatsStore(tmp_path / "d.db")
    app = create_app(store, make_service=fake_factory(Script(), **kw), sessions=sessions)
    with TestClient(app) as client:
        game = client.post("/api/games", json={"seed": 1}).json()["game"]
        name = client.post(f"/api/games/{game}/save").json()["name"]
        assert client.delete(f"/api/saves/{name}").status_code == 204
        assert client.get("/api/saves").json() == []
        again = client.delete(f"/api/saves/{name}")
        assert (again.status_code, again.json()["code"]) == (422, "bad_save")
        client.cookies.clear()  # no session at all: the same answer as for a game that is not yours
        stranger = client.delete(f"/api/saves/{name}")
        assert (stranger.status_code, stranger.json()["code"]) == (404, "unknown_game")
        assert (
            client.post("/api/games", json={"seed": 2}).status_code == 200
        )  # a session of its own
        other = client.delete(f"/api/saves/{name}")
        assert (other.status_code, other.json()["code"]) == (422, "bad_save")


def test_the_save_caps_come_from_the_settings_and_default_to_unlimited():
    from gumshoe.config import Settings

    settings = Settings(_env_file=None, session_saves=3, ip_saves=7)
    caps = Caps.from_settings(settings)
    assert (caps.saves_per_session, caps.saves_per_ip) == (3, 7)
    assert (Caps().saves_per_session, Caps().saves_per_ip) == (0, 0)
