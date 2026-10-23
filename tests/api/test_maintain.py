import asyncio
import logging

from tests.agent.fakes import Script
from tests.api.helpers import OWNER, serving
from tests.decider.fakes import FakeClock


async def test_the_loop_expires_idle_games_and_purges_saves_on_schedule():
    clock = FakeClock()
    purged: list[float] = []
    purge_seen = asyncio.Event()
    async with serving(Script(), clock=clock, idle_s=60.0) as s:

        async def fake_purge(retention_s):
            purged.append(retention_s)
            if len(purged) == 2:  # the scheduled purge, after at least one expiry pass
                purge_seen.set()
            return 0

        s.service.purge_saves = fake_purge  # type: ignore[method-assign]
        await s.service.new_game(1, owner=OWNER)

        async def sleep(_):
            clock.advance(61)
            await asyncio.sleep(0)  # a real sleep always yields: without this the loop would spin

        task = asyncio.create_task(
            s.service.maintain(interval_s=1, purge_every_s=100, retention_s=5.0, sleep=sleep)
        )
        await asyncio.wait_for(purge_seen.wait(), 2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await s.service.games(owner=OWNER) == []
        assert purged == [5.0, 5.0]  # the first purge is the one at startup


async def test_a_failing_step_is_logged_and_the_loop_carries_on(caplog):
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=60.0) as s:
        calls = {"n": 0}
        second_call = asyncio.Event()

        async def boom():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("disk on fire")
            second_call.set()
            return 0

        s.service.expire_idle = boom  # type: ignore[method-assign]

        async def sleep(_):
            await asyncio.sleep(0)

        with caplog.at_level(logging.ERROR):
            task = asyncio.create_task(s.service.maintain(interval_s=1, sleep=sleep))
            await asyncio.wait_for(second_call.wait(), 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert calls["n"] >= 2 and "RuntimeError" in caplog.text and "disk on fire" not in caplog.text
