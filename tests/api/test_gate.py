import asyncio

import pytest

from gumshoe.api.ratelimit import Busy, TurnGate


async def test_a_free_slot_is_taken_at_once():
    gate = TurnGate(parallel=1, queue=1, wait_s=1)
    t = gate.admit()
    assert await t.wait(asyncio.Event()) == "ready"
    assert (gate.running, gate.queued) == (1, 0)
    t.close()
    assert (gate.running, gate.queued) == (0, 0)


async def test_the_queue_is_bounded_and_full_means_busy_at_once():
    gate = TurnGate(parallel=1, queue=1, wait_s=1)
    first = gate.admit()
    await first.wait(asyncio.Event())
    second = gate.admit()  # takes the one queue place
    with pytest.raises(Busy):
        gate.admit()
    second.close()
    gate.admit().close()  # the place is free again


async def test_a_waiting_turn_runs_when_a_slot_frees_and_is_told_its_place():
    gate = TurnGate(parallel=1, queue=2, wait_s=5)
    first = gate.admit()
    await first.wait(asyncio.Event())
    places: list[int] = []
    second = gate.admit()
    waiting = asyncio.create_task(second.wait(asyncio.Event(), places.append))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert places == [1] and not waiting.done()
    first.close()
    assert await asyncio.wait_for(waiting, 1) == "ready"
    assert (gate.running, gate.queued) == (1, 0)


async def test_waiting_longer_than_the_limit_times_out_and_frees_the_place():
    gate = TurnGate(parallel=1, queue=1, wait_s=0.05)
    holder = gate.admit()
    await holder.wait(asyncio.Event())
    late = gate.admit()
    assert await asyncio.wait_for(late.wait(asyncio.Event()), 2) == "timeout"
    assert gate.queued == 0
    gate.admit().close()  # the place really is free


async def test_a_reader_who_leaves_frees_the_place_at_once():
    gate = TurnGate(parallel=1, queue=1, wait_s=30)
    holder = gate.admit()
    await holder.wait(asyncio.Event())
    gone = asyncio.Event()
    waiter = gate.admit()
    task = asyncio.create_task(waiter.wait(gone))
    await asyncio.sleep(0)
    gone.set()
    assert await asyncio.wait_for(task, 1) == "left"
    assert gate.queued == 0


async def test_cancelling_a_wait_frees_the_place():
    gate = TurnGate(parallel=1, queue=1, wait_s=30)
    holder = gate.admit()
    await holder.wait(asyncio.Event())
    waiter = gate.admit()
    task = asyncio.create_task(waiter.wait(asyncio.Event()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert gate.queued == 0


async def test_close_is_idempotent_in_every_state():
    gate = TurnGate(parallel=1, queue=1, wait_s=1)
    never_waited = gate.admit()
    never_waited.close()
    never_waited.close()
    ran = gate.admit()
    await ran.wait(asyncio.Event())
    ran.close()
    ran.close()
    assert (gate.running, gate.queued) == (0, 0)
    gate.admit().close()  # the semaphore was released exactly once


async def test_no_gate_when_parallel_is_zero():
    gate = TurnGate(parallel=0, queue=0, wait_s=1)
    tickets = [gate.admit() for _ in range(20)]
    assert [await t.wait(asyncio.Event()) for t in tickets] == ["ready"] * 20
