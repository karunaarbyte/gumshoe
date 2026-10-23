import asyncio

from gumshoe.agent.events import Confirm
from gumshoe.api import create_app
from gumshoe.decider import client_key
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script, ScriptedDecider
from tests.api.client import TestClient
from tests.api.helpers import OWNER, fake_factory, serving


class KeyRecordingDecider(ScriptedDecider):
    def __init__(self, script):
        super().__init__(script)
        self.keys: list[str] = []
        self.mode = "normal"

    async def decide(self, state, questions, *, node="adhoc", decision_id=None):
        self.keys.append(client_key.get())
        return await super().decide(state, questions, node=node, decision_id=decision_id)


async def test_a_turn_sets_the_client_key_for_its_decisions_and_restores_it():
    decider = KeyRecordingDecider(Script().understand(intent="notebook"))
    async with serving(Script(), decider=decider) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="9.9.9.9")
        async for _ in s.service.start_turn(g.game, "notebook", owner=OWNER, ip="9.9.9.9"):
            pass
    assert decider.keys and set(decider.keys) == {"9.9.9.9"}
    assert client_key.get() == ""


async def test_a_confirm_turn_runs_under_the_request_ip_too(monkeypatch):
    decider = KeyRecordingDecider(Script().understand(intent="give_up"))
    async with serving(Script(), decider=decider) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="8.8.8.8")
        events = [
            e async for e in s.service.start_turn(g.game, "I give up", owner=OWNER, ip="8.8.8.8")
        ]
        [confirm] = [e for e in events if isinstance(e, Confirm)]
        client = s.service._deps.client
        real_give_up = client.give_up
        seen: list[str] = []

        async def give_up(*args, **kwargs):
            seen.append(client_key.get())
            return await real_give_up(*args, **kwargs)

        monkeypatch.setattr(client, "give_up", give_up)
        async with asyncio.timeout(10):
            async for _ in s.service.start_confirm(
                g.game, confirm.pending_id, "yes", owner=OWNER, ip="7.7.7.7"
            ):
                pass
    assert decider.keys == ["8.8.8.8"]  # the turn that asked
    assert seen == ["7.7.7.7"]  # the confirm runs under its own request's ip
    assert client_key.get() == ""


async def test_a_turn_with_no_ip_runs_with_no_client_key():
    decider = KeyRecordingDecider(Script().understand(intent="notebook"))
    async with serving(Script(), decider=decider) as s:
        g = await s.service.new_game(1, owner=OWNER)
        async for _ in s.service.start_turn(g.game, "notebook", owner=OWNER):
            pass
    assert decider.keys and set(decider.keys) == {""}


async def test_the_key_does_not_leak_into_the_next_turn():
    decider = KeyRecordingDecider(Script().understand(intent="notebook"))
    async with serving(Script(), decider=decider) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="9.9.9.9")
        async for _ in s.service.start_turn(g.game, "notebook", owner=OWNER, ip="9.9.9.9"):
            pass
        assert client_key.get() == ""  # the caller's context never saw it
        async for _ in s.service.start_turn(g.game, "notebook", owner=OWNER):
            pass
    assert decider.keys[0] == "9.9.9.9" and decider.keys[-1] == ""


async def test_the_service_reports_the_deciders_mode():
    decider = KeyRecordingDecider(Script())
    async with serving(Script(), decider=decider) as s:
        assert s.service.decider_mode() == "normal"
        decider.mode = "slow"
        assert s.service.decider_mode() == "slow"


async def test_a_decider_without_a_mode_is_normal():
    async with serving(Script()) as s:
        assert s.service.decider_mode() == "normal"


def test_health_reports_the_mode(tmp_path):
    async def up():
        return True

    store = SqliteStatsStore(tmp_path / "d.db")
    app = create_app(store, make_service=fake_factory(Script()), personas_up=up)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["mode"] == "normal"
        app.state.service.decider_mode = lambda: "slow"
        assert client.get("/api/health").json()["mode"] == "slow"


def test_health_mode_is_normal_when_the_game_is_off(tmp_path):
    from gumshoe.config import Settings

    async def up():
        return True

    store = SqliteStatsStore(tmp_path / "d.db")
    app = create_app(store, settings=Settings(_env_file=None), personas_up=up)  # no Jev key: off
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["game"] == "off" and body["mode"] == "normal"
