import asyncio

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import ApiError
from gumshoe.api.service import COLD_TEXT, _Tombstones
from tests.agent.fakes import Script
from tests.api.helpers import OWNER, GatedDecider, idle, serving
from tests.decider.fakes import FakeClock

IDLE = 30 * 60.0


async def test_an_idle_game_is_closed_and_frees_its_slot():
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=IDLE) as s:
        await s.service.new_game(1, owner=OWNER)
        clock.advance(IDLE - 1)
        assert await s.service.expire_idle() == 0
        clock.advance(2)
        assert await s.service.expire_idle() == 1
        assert await s.service.games(owner=OWNER) == []
        assert s.host._games == {}  # the engine game was closed too


async def test_the_owner_gets_cold_and_a_stranger_gets_the_ordinary_missing_game_error():
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=IDLE) as s:
        g = await s.service.new_game(1, owner=OWNER)
        clock.advance(IDLE + 1)
        await s.service.expire_idle()
        with pytest.raises(ApiError) as owner:
            await s.service.state(g.game, owner=OWNER)
        assert (owner.value.status, owner.value.code, owner.value.message) == (
            410,
            "cold",
            COLD_TEXT,
        )
        with pytest.raises(ToolFailure) as stranger:
            await s.service.state(g.game, owner="someone-else")
        with pytest.raises(ToolFailure) as missing:
            await s.service.state("0123456789abcdef", owner="someone-else")
    assert (stranger.value.code, stranger.value.message) == (
        missing.value.code,
        missing.value.message,
    )


async def test_idleness_is_measured_from_the_end_of_the_last_turn():
    clock = FakeClock()
    decider = GatedDecider(Script().understand(intent="notebook"))
    async with serving(Script(), clock=clock, idle_s=IDLE, decider=decider) as s:
        g = await s.service.new_game(1, owner=OWNER)
        stream = s.service.start_turn(g.game, "notebook", owner=OWNER)
        await decider.entered.wait()
        clock.advance(IDLE + 600)  # the turn has run past the idle limit
        assert await s.service.expire_idle() == 0  # busy: never expired
        decider.release.set()
        async for _ in stream:
            pass
        await idle(s.service)
        assert await s.service.expire_idle() == 0  # the turn only just ended
        clock.advance(IDLE + 1)
        assert await s.service.expire_idle() == 1


async def test_a_game_with_a_waiting_save_or_delete_lock_is_left_alone_until_free():
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=IDLE) as s:
        g = await s.service.new_game(1, owner=OWNER)
        slot = s.service._slots[g.game]
        async with slot.lock:  # something (a save) holds the game right now
            clock.advance(IDLE + 1)
            expiring = asyncio.create_task(s.service.expire_idle())
            await asyncio.sleep(0.05)
            assert not expiring.done()
        assert await expiring == 1


async def test_a_turn_admitted_while_expiry_waits_for_the_lock_keeps_the_game():
    clock = FakeClock()
    script = Script().understand(intent="notebook")
    async with serving(script, clock=clock, idle_s=IDLE) as s:
        g = await s.service.new_game(1, owner=OWNER)
        slot = s.service._slots[g.game]
        clock.advance(IDLE + 1)
        await slot.lock.acquire()  # something holds the game, so expiry has to wait
        expiring = asyncio.create_task(s.service.expire_idle())
        await asyncio.sleep(0.02)
        stream = s.service.start_turn(
            g.game, "notebook", owner=OWNER
        )  # admitted: the slot is busy now
        slot.lock.release()
        async with asyncio.timeout(5):
            events = [e async for e in stream]
            closed = await expiring
        assert closed == 0  # the re-check under the lock saw the busy slot
        assert events[-1].kind == "done" and "tool_result" in [e.kind for e in events]
        assert g.game in s.service._slots


async def test_zero_idle_never_expires():
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=0.0) as s:
        await s.service.new_game(1, owner=OWNER)
        clock.advance(10**9)
        assert await s.service.expire_idle() == 0


def test_tombstones_expire_after_their_ttl_and_the_map_is_capped():
    clock = FakeClock()
    t = _Tombstones(cap=3, ttl_s=100.0, clock=clock)
    for i in range(5):
        t.add("o", f"g{i}")
    assert not t.has("o", "g0") and not t.has("o", "g1")  # the oldest were evicted
    assert t.has("o", "g4")
    clock.advance(101)
    assert not t.has("o", "g4")


def test_a_tombstone_belongs_to_its_owner():
    t = _Tombstones(cap=10, ttl_s=100.0, clock=FakeClock())
    t.add("alice", "g")
    assert t.has("alice", "g") and not t.has("bob", "g")
