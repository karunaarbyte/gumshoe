import asyncio
import logging

import pytest

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


async def test_cancellation_from_the_sleep_ends_the_loop():
    async with serving(Script(), clock=FakeClock(), idle_s=60.0) as s:

        async def sleep(_):
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(s.service.maintain(interval_s=1, sleep=sleep), 2)


async def test_cancellation_inside_a_step_is_not_swallowed():
    async with serving(Script(), clock=FakeClock(), idle_s=60.0) as s:

        async def cancelled():
            raise asyncio.CancelledError

        s.service.expire_idle = cancelled  # type: ignore[method-assign]

        async def sleep(_):
            await asyncio.sleep(0)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(s.service.maintain(interval_s=1, sleep=sleep), 2)


async def test_a_failing_expiry_does_not_skip_the_purge_in_the_same_pass():
    clock = FakeClock()
    async with serving(Script(), clock=clock, idle_s=60.0) as s:
        purges: list[float] = []
        second_pass = asyncio.Event()
        expiries = {"n": 0}

        async def boom():
            expiries["n"] += 1
            if expiries["n"] == 2:
                second_pass.set()
            raise RuntimeError("disk on fire")

        async def fake_purge(retention_s):
            purges.append(retention_s)
            return 0

        s.service.expire_idle = boom  # type: ignore[method-assign]
        s.service.purge_saves = fake_purge  # type: ignore[method-assign]

        async def sleep(_):
            clock.advance(10)  # every pass is due for a purge
            await asyncio.sleep(0)

        task = asyncio.create_task(
            s.service.maintain(interval_s=1, purge_every_s=5, retention_s=7.0, sleep=sleep)
        )
        await asyncio.wait_for(second_pass.wait(), 2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    # the startup purge, plus the first pass's purge, which ran though its expiry failed
    assert len(purges) >= 2 and expiries["n"] >= 2


async def test_maintain_also_runs_the_housekeeping_callback_on_the_purge_schedule():
    clock = FakeClock()
    ran = asyncio.Event()
    async with serving(Script(), clock=clock) as s:

        async def sleep(_):
            clock.advance(200)
            await asyncio.sleep(0)

        task = asyncio.create_task(
            s.service.maintain(interval_s=1, purge_every_s=100, housekeeping=ran.set, sleep=sleep)
        )
        await asyncio.wait_for(ran.wait(), 2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_failing_housekeeping_is_logged_and_the_next_pass_still_runs(caplog):
    clock = FakeClock()
    calls = {"n": 0}
    second = asyncio.Event()

    def housekeeping():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("secret-path /tmp/x")
        second.set()

    async with serving(Script(), clock=clock) as s:

        async def sleep(_):
            clock.advance(200)
            await asyncio.sleep(0)

        with caplog.at_level(logging.ERROR):
            task = asyncio.create_task(
                s.service.maintain(
                    interval_s=1, purge_every_s=100, housekeeping=housekeeping, sleep=sleep
                )
            )
            await asyncio.wait_for(second.wait(), 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert calls["n"] >= 2
    assert "housekeeping failed: RuntimeError" in caplog.text
    assert "secret-path" not in caplog.text


async def test_housekeeping_is_skipped_until_the_purge_cadence_has_elapsed():
    clock = FakeClock()
    ran = asyncio.Event()
    passes = 0
    two_passes = asyncio.Event()
    async with serving(Script(), clock=clock) as s:

        async def sleep(_):
            nonlocal passes
            passes += 1
            if passes >= 3:
                two_passes.set()
            clock.advance(1)  # far below purge_every_s
            await asyncio.sleep(0)

        task = asyncio.create_task(
            s.service.maintain(interval_s=1, purge_every_s=100, housekeeping=ran.set, sleep=sleep)
        )
        await asyncio.wait_for(two_passes.wait(), 2)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not ran.is_set()
