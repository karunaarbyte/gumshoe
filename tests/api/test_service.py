import asyncio

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api.service import AgentService
from gumshoe.mcp_server import GameError
from tests.agent.fakes import Script
from tests.api.helpers import GatedDecider, serving


def kinds(events):
    return [e.kind for e in events]


async def collect(service: AgentService, game: str, text: str):
    async with asyncio.timeout(10):  # a regression fails the test instead of hanging the suite
        return [event async for event in service.start_turn(game, text)]


async def test_a_turn_streams_the_agents_events_and_ends_with_done():
    script = Script().understand(intent="search", target="place_1")
    async with serving(script) as s:
        new = await s.service.new_game(1)
        events = await collect(s.service, new.game, "search the first place")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "done"]
    assert script.left() == {}


async def test_state_returns_the_brief_and_the_notebook():
    async with serving(Script()) as s:
        new = await s.service.new_game(1)
        state = await s.service.state(new.game)
    assert state.brief == new.brief and state.notebook.sections is not None


async def test_an_unknown_game_fails_at_once_not_in_the_stream():
    async with serving(Script()) as s:
        with pytest.raises(ToolFailure) as caught:
            s.service.start_turn("nope", "hello")
        assert caught.value.code == "unknown_game"
        with pytest.raises(ToolFailure):
            await s.service.state("nope")
        with pytest.raises(ToolFailure):
            await s.service.delete_game("nope")
        with pytest.raises(ToolFailure):
            await s.service.save_game("nope")


async def test_chat_memory_lives_across_turns():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    async with serving(script) as s:
        new = await s.service.new_game(1)
        await collect(s.service, new.game, "search the first place")
        await collect(s.service, new.game, "show my notebook")
    second_state = s.decider.calls[1][1]
    assert "Earlier the player said: search the first place" in second_state


async def test_two_games_keep_separate_memory():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    async with serving(script) as s:
        a = await s.service.new_game(1)
        b = await s.service.new_game(2)
        await collect(s.service, a.game, "search the first place")
        await collect(s.service, b.game, "show my notebook")
    assert "Earlier the player said" not in s.decider.calls[1][1]


async def test_a_second_turn_waits_for_the_first():
    script = Script().understand(intent="notebook").understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1)
        first = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        second = asyncio.create_task(collect(s.service, new.game, "two"))
        await asyncio.sleep(0.05)
        assert gated.started == 1  # the second turn has not reached the decider
        assert not second.done()
        gated.release.set()
        one, two = await asyncio.gather(first, second)
    assert kinds(one)[-1] == kinds(two)[-1] == "done"
    assert [c[1].splitlines()[0] for c in gated.calls] == ["Player says: one", "Player says: two"]


async def test_a_disconnect_does_not_stop_the_turn():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1)
        stream = s.service.start_turn(new.game, "search the first place")
        reader = asyncio.create_task(anext(stream))  # the client reads, then drops
        await gated.entered.wait()
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await stream.aclose()
        gated.release.set()
        await s.service.idle()
        await collect(s.service, new.game, "show my notebook")
    assert "Earlier the player said: search the first place" in gated.calls[1][1]


async def test_delete_closes_the_game_and_forgets_it():
    async with serving(Script()) as s:
        new = await s.service.new_game(1)
        await s.service.delete_game(new.game)
        with pytest.raises(ToolFailure) as caught:
            s.service.start_turn(new.game, "hello")
        assert caught.value.code == "unknown_game"
        with pytest.raises(GameError):
            s.host.case_brief(new.game)  # the host raises its own error, not the client's


async def test_delete_waits_for_a_running_turn_and_ends_a_queued_one(monkeypatch):
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1)
        running = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()  # the running turn has read the brief already
        client = s.service._deps.client
        real_brief = client.case_brief
        briefs: list[str] = []

        async def counted_brief(game):
            briefs.append(game)
            return await real_brief(game)

        monkeypatch.setattr(client, "case_brief", counted_brief)
        queued = asyncio.create_task(collect(s.service, new.game, "two"))
        deleting = asyncio.create_task(s.service.delete_game(new.game))
        await asyncio.sleep(0.05)
        assert not deleting.done() and not queued.done()
        gated.release.set()
        one, two, _ = await asyncio.gather(running, queued, deleting)
    assert kinds(one)[-1] == "done" and len(one) > 1
    assert kinds(two) == ["done"]  # saw the game gone, ran nothing
    assert gated.started == 1
    assert briefs == []  # the queued turn never reached the game server


async def test_a_turn_that_crashes_still_ends_the_stream():
    script = Script()  # empty: ScriptExhausted is a BaseException and escapes take_turn
    async with serving(script) as s:
        new = await s.service.new_game(1)
        events = await collect(s.service, new.game, "hello")
        await asyncio.wait_for(s.service.idle(), timeout=5.0)
    assert events == []  # the stream ended instead of hanging
    assert s.service  # still usable


async def test_save_and_load_register_the_loaded_game(tmp_path):
    script = Script().understand(intent="notebook")
    async with serving(script, saves_dir=tmp_path) as s:
        new = await s.service.new_game(1)
        saved = await s.service.save_game(new.game)
        loaded = await s.service.load_game(saved.name)
        assert loaded.game != new.game
        events = await collect(s.service, loaded.game, "show my notebook")
    assert kinds(events)[-1] == "done"


async def test_save_waits_for_a_running_turn(tmp_path):
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated, saves_dir=tmp_path) as s:
        new = await s.service.new_game(1)
        running = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        saving = asyncio.create_task(s.service.save_game(new.game))
        await asyncio.sleep(0.05)
        assert not saving.done()  # a save is taken between turns, never mid-turn
        gated.release.set()
        await running
        saved = await saving
    assert len(saved.name) == 16


async def test_aclose_cancels_a_running_turn_without_hanging():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated, grace_s=2.0) as s:
        new = await s.service.new_game(1)
        task = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        await asyncio.wait_for(s.service.aclose(), timeout=3.0)
        assert await asyncio.wait_for(task, timeout=1.0) == []  # ended: the turn was cancelled


async def test_ten_games_run_turns_at_once():
    script = Script()
    for _ in range(10):
        script.understand(intent="notebook")
    async with serving(script) as s:
        games = [(await s.service.new_game(i)).game for i in range(1, 11)]
        results = await asyncio.gather(*(collect(s.service, g, "show my notebook") for g in games))
    assert all(kinds(r)[-1] == "done" and "tool_result" in kinds(r) for r in results)
