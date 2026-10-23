import asyncio
import contextlib

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
    gate = TurnGate(parallel=1, queue=1, wait_s=0.001)
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
    gate = TurnGate(parallel=1, queue=1, wait_s=0.01)
    never_waited = gate.admit()
    never_waited.close()
    never_waited.close()
    ran = gate.admit()
    await ran.wait(asyncio.Event())
    ran.close()
    ran.close()
    assert (gate.running, gate.queued) == (0, 0)
    # the semaphore was released exactly once: only one of two new tickets can run
    a, b = gate.admit(), gate.admit()
    assert await asyncio.wait_for(a.wait(asyncio.Event()), 1) == "ready"
    assert await asyncio.wait_for(b.wait(asyncio.Event(), None), 1) == "timeout"


async def test_no_gate_when_parallel_is_zero():
    gate = TurnGate(parallel=0, queue=0, wait_s=1)
    tickets = [gate.admit() for _ in range(20)]
    assert [await t.wait(asyncio.Event()) for t in tickets] == ["ready"] * 20


def _sem(gate: TurnGate) -> int:
    return gate.semaphore._value  # noqa: SLF001


async def _settle(n: int = 3) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def _waiting(gate: TurnGate):
    holder = gate.admit()
    await holder.wait(asyncio.Event())
    waiter = gate.admit()
    task = asyncio.create_task(waiter.wait(asyncio.Event()))
    await _settle()
    return holder, waiter, task


async def _cancelled(task: asyncio.Task) -> None:
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)


async def test_a_second_cancel_after_the_hand_over_does_not_leak_the_slot():
    for first in range(4):
        for second in range(4):
            gate = TurnGate(parallel=1, queue=1, wait_s=30)
            holder, waiter, task = await _waiting(gate)
            holder.close()  # hands the slot to the waiter
            await _settle(first)
            task.cancel()
            await _settle(second)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            waiter.close()
            await _settle()
            assert (gate.running, gate.queued, _sem(gate)) == (0, 0, 1), (first, second)


async def test_cancel_at_the_moment_of_release_does_not_leak_the_slot():
    gate = TurnGate(parallel=1, queue=1, wait_s=30)
    holder, waiter, task = await _waiting(gate)
    holder.close()
    task.cancel()
    await _cancelled(task)
    waiter.close()
    await _settle()
    assert (gate.running, gate.queued, _sem(gate)) == (0, 0, 1)


async def test_a_timeout_racing_a_release_never_loses_the_slot():
    for _ in range(50):
        gate = TurnGate(parallel=1, queue=1, wait_s=0.001)
        holder = gate.admit()
        await holder.wait(asyncio.Event())
        waiter = gate.admit()
        task = asyncio.create_task(waiter.wait(asyncio.Event()))
        await asyncio.sleep(0.001)
        holder.close()
        result = await asyncio.wait_for(task, 1)
        assert result in ("ready", "timeout")
        waiter.close()
        await _settle()
        assert (gate.running, gate.queued, _sem(gate)) == (0, 0, 1)


async def test_closing_a_ticket_while_it_waits_keeps_the_counts_sane():
    gate = TurnGate(parallel=1, queue=2, wait_s=30)
    holder, waiter, task = await _waiting(gate)
    waiter.close()
    holder.close()
    assert await asyncio.wait_for(task, 1) == "left"
    waiter.close()
    assert (gate.running, gate.queued, _sem(gate)) == (0, 0, 1)
