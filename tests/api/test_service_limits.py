import asyncio
import contextlib

import pytest

import gumshoe.api.service as service_module
from gumshoe.agent import ToolFailure
from gumshoe.api.errors import ApiError
from gumshoe.api.ratelimit import Quotas, TurnGate
from gumshoe.api.service import BUSY_TEXT, Caps
from gumshoe.config import Settings
from tests.agent.fakes import Script
from tests.api.helpers import OWNER, GatedDecider, HeldSave, idle, serving


def kinds(events):
    return [e.kind for e in events]


async def drain(stream):
    async with asyncio.timeout(10):
        return [e async for e in stream]


async def test_open_games_per_session_are_capped():
    async with serving(Script(), caps=Caps(games_per_session=2)) as s:
        await s.service.new_game(1, owner=OWNER)
        await s.service.new_game(2, owner=OWNER)
        with pytest.raises(ApiError) as caught:
            await s.service.new_game(3, owner=OWNER)
        assert (caught.value.status, caught.value.code) == (429, "quota")
        await s.service.new_game(3, owner="someone-else")


async def test_concurrent_creations_cannot_slip_past_the_cap():
    async with serving(Script(), caps=Caps(games_per_session=3, games_per_ip=3)) as s:
        results = await asyncio.gather(
            *(s.service.new_game(i, owner=OWNER, ip="1.1.1.1") for i in range(10)),
            return_exceptions=True,
        )
        refused = [r for r in results if isinstance(r, ApiError)]
        assert len(refused) == 7 and all(r.code == "quota" for r in refused)
        assert len(await s.service.games(owner=OWNER)) == 3
        # the reservations were released: deleting one game makes room for exactly one more
        [first, *_] = await s.service.games(owner=OWNER)
        await s.service.delete_game(first.game, owner=OWNER)
        await s.service.new_game(99, owner=OWNER, ip="1.1.1.1")


async def test_the_counters_do_not_grow_with_the_number_of_clients():
    script = Script()
    for _ in range(5):
        script.understand(intent="notebook")
    async with serving(script, caps=Caps(games_per_session=1, turns_in_flight_per_ip=5)) as s:
        for i in range(5):
            g = await s.service.new_game(i, owner=f"owner-{i}", ip=f"9.9.9.{i}")
            await drain(
                s.service.start_turn(g.game, "notebook", owner=f"owner-{i}", ip=f"9.9.9.{i}")
            )
        await idle(s.service)
        assert not s.service._flying_by_owner and not s.service._flying_by_ip
        assert not s.service._reserved_by_owner and not s.service._reserved_by_ip


async def test_open_games_per_ip_are_capped_across_sessions():
    async with serving(Script(), caps=Caps(games_per_ip=2)) as s:
        await s.service.new_game(1, owner="a", ip="1.1.1.1")
        await s.service.new_game(2, owner="b", ip="1.1.1.1")
        with pytest.raises(ApiError) as caught:
            await s.service.new_game(3, owner="c", ip="1.1.1.1")
        assert caught.value.code == "quota"
        await s.service.new_game(3, owner="c", ip="2.2.2.2")


async def test_deleting_a_game_frees_its_quota_place():
    async with serving(Script(), caps=Caps(games_per_session=1)) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await s.service.delete_game(g.game, owner=OWNER)
        await s.service.new_game(2, owner=OWNER)


async def test_game_creation_rate_is_checked():
    quotas = Quotas(Settings(_env_file=None, session_games_per_hour=1))
    async with serving(Script(), quotas=quotas) as s:
        await s.service.new_game(1, owner=OWNER)
        with pytest.raises(ApiError) as caught:
            await s.service.new_game(2, owner=OWNER)
    assert caught.value.code == "rate_limited" and caught.value.retry_after


async def test_turn_rate_per_session_is_checked_after_the_game_is_found():
    quotas = Quotas(Settings(_env_file=None, session_turns_per_minute=1))
    script = Script().understand(intent="notebook").understand(intent="notebook")
    async with serving(script, quotas=quotas) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await drain(s.service.start_turn(g.game, "notebook", owner=OWNER))
        with pytest.raises(ApiError) as caught:
            s.service.start_turn(g.game, "notebook", owner=OWNER)
        assert caught.value.code == "rate_limited"
        with pytest.raises(ToolFailure):  # an unknown game still answers 404, not 429
            s.service.start_turn("nope", "x", owner=OWNER)


async def test_one_session_cannot_hold_two_turns_at_once():
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, caps=Caps(turns_per_session=1)) as s:
        a = await s.service.new_game(1, owner=OWNER)
        b = await s.service.new_game(2, owner=OWNER)
        first = s.service.start_turn(a.game, "notebook", owner=OWNER)
        with pytest.raises(ApiError) as caught:
            s.service.start_turn(b.game, "notebook", owner=OWNER)
        assert (caught.value.status, caught.value.code) == (409, "turn_in_progress")
        decider.release.set()
        await drain(first)
        await idle(s.service)
        await drain(s.service.start_turn(b.game, "notebook", owner=OWNER))


async def test_turns_in_flight_per_ip_are_capped():
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, caps=Caps(turns_in_flight_per_ip=1)) as s:
        a = await s.service.new_game(1, owner="a", ip="1.1.1.1")
        b = await s.service.new_game(2, owner="b", ip="1.1.1.1")
        first = s.service.start_turn(a.game, "notebook", owner="a", ip="1.1.1.1")
        with pytest.raises(ApiError) as caught:
            s.service.start_turn(b.game, "notebook", owner="b", ip="1.1.1.1")
        assert (caught.value.status, caught.value.code) == (429, "busy")
        decider.release.set()
        await drain(first)


async def test_a_full_queue_is_refused_at_once_with_busy_and_retry_after():
    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, gate=gate) as s:
        a = await s.service.new_game(1, owner="a")
        b = await s.service.new_game(2, owner="b")
        first = s.service.start_turn(a.game, "notebook", owner="a")
        await decider.entered.wait()
        with pytest.raises(ApiError) as caught:
            s.service.start_turn(b.game, "notebook", owner="b")
        assert (caught.value.status, caught.value.code, caught.value.retry_after) == (
            429,
            "busy",
            5,
        )
        decider.release.set()
        await drain(first)


async def test_a_queued_turn_says_so_runs_later_and_the_queued_event_is_not_kept():
    gate = TurnGate(parallel=1, queue=1, wait_s=5)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, gate=gate) as s:
        a = await s.service.new_game(1, owner="a")
        b = await s.service.new_game(2, owner="b")
        first = s.service.start_turn(a.game, "notebook", owner="a")
        await decider.entered.wait()
        second_stream = s.service.start_turn(b.game, "notebook", owner="b")
        second = asyncio.create_task(drain(second_stream))
        await asyncio.sleep(0.05)
        decider.release.set()
        await drain(first)
        events = await second
        assert kinds(events)[0] == "queued" and events[0].position == 1
        assert kinds(events)[-1] == "done" and "tool_result" in kinds(events)
        kept = s.service.turns(b.game, owner="b")[0].events
        assert "queued" not in kinds(kept)


async def test_a_turn_that_waits_too_long_ends_with_a_busy_message_and_is_not_recorded():
    gate = TurnGate(parallel=1, queue=1, wait_s=0.05)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, gate=gate) as s:
        a = await s.service.new_game(1, owner="a")
        b = await s.service.new_game(2, owner="b")
        first = s.service.start_turn(a.game, "notebook", owner="a")
        await decider.entered.wait()
        events = await drain(s.service.start_turn(b.game, "notebook", owner="b"))
        assert kinds(events) == ["queued", "clarify", "done"]
        assert events[1].reason == "error" and events[1].text == BUSY_TEXT
        assert s.service.turns(b.game, owner="b") == []
        decider.release.set()
        await drain(first)


async def test_a_reader_who_leaves_while_queued_gives_up_the_place():
    gate = TurnGate(parallel=1, queue=1, wait_s=30)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    async with serving(Script(), decider=decider, gate=gate) as s:
        a = await s.service.new_game(1, owner="a")
        b = await s.service.new_game(2, owner="b")
        first = s.service.start_turn(a.game, "notebook", owner="a")
        await decider.entered.wait()
        stream = s.service.start_turn(b.game, "notebook", owner="b")
        await anext(stream)  # the `queued` event
        await stream.aclose()  # the client leaves
        await asyncio.sleep(0.05)
        assert gate.queued == 0
        decider.release.set()
        await drain(first)
        await idle(s.service)
        assert s.service.turns(b.game, owner="b") == []


async def test_the_gate_place_is_released_when_the_turn_ends():
    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    script = Script().understand(intent="notebook").understand(intent="notebook")
    async with serving(script, gate=gate) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await drain(s.service.start_turn(g.game, "notebook", owner=OWNER))
        await idle(s.service)
        assert (gate.running, gate.queued) == (0, 0)
        await drain(s.service.start_turn(g.game, "notebook", owner=OWNER))


async def test_the_gate_is_taken_after_the_game_lock_so_a_long_save_never_holds_a_slot(
    tmp_path,
):
    gate = TurnGate(parallel=1, queue=1, wait_s=5)
    async with serving(Script().understand(intent="notebook"), gate=gate, saves_dir=tmp_path) as s:
        g = await s.service.new_game(1, owner=OWNER)
        await s.service.save_game(g.game, owner=OWNER)
        assert (gate.running, gate.queued) == (0, 0)


def at_baseline(service, gate):
    assert (gate.running, gate.queued) == (0, 0)
    assert not service._flying_by_owner and not service._flying_by_ip
    assert not service._reserved_by_owner and not service._reserved_by_ip


async def test_a_turn_cancelled_while_queued_gives_back_every_place():
    gate = TurnGate(parallel=1, queue=1, wait_s=30)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    caps = Caps(turns_per_session=1, turns_in_flight_per_ip=1)
    async with serving(Script(), decider=decider, gate=gate, caps=caps) as s:
        a = await s.service.new_game(1, owner="a", ip="1.1.1.1")
        b = await s.service.new_game(2, owner="b", ip="2.2.2.2")
        first = s.service.start_turn(a.game, "notebook", owner="a", ip="1.1.1.1")
        await decider.entered.wait()
        known = set(s.service._tasks)
        stream = s.service.start_turn(b.game, "notebook", owner="b", ip="2.2.2.2")
        assert (await anext(stream)).kind == "queued"
        [queued_task] = s.service._tasks - known
        queued_task.cancel()
        events = await drain(stream)
        assert kinds(events) == ["clarify", "done"]
        assert gate.queued == 0 and "b" not in s.service._flying_by_owner
        decider.release.set()
        await drain(first)
        await idle(s.service)
        at_baseline(s.service, gate)


async def test_a_client_who_leaves_mid_turn_gives_back_every_place_when_it_ends():
    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    decider = GatedDecider(Script().understand(intent="notebook").understand(intent="notebook"))
    caps = Caps(turns_per_session=1, turns_in_flight_per_ip=1)
    async with serving(Script(), decider=decider, gate=gate, caps=caps) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="1.1.1.1")
        stream = s.service.start_turn(g.game, "notebook", owner=OWNER, ip="1.1.1.1")
        reading = asyncio.ensure_future(anext(stream))
        await decider.entered.wait()
        reading.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await reading
        await stream.aclose()  # the client leaves; the turn runs on
        assert gate.running == 1
        decider.release.set()
        await idle(s.service)
        at_baseline(s.service, gate)
        await drain(s.service.start_turn(g.game, "notebook", owner=OWNER, ip="1.1.1.1"))


async def test_a_turn_that_raises_gives_back_every_place(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(service_module, "take_turn", broken)
    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    caps = Caps(turns_per_session=1, turns_in_flight_per_ip=1)
    async with serving(Script(), gate=gate, caps=caps) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="1.1.1.1")
        await drain(s.service.start_turn(g.game, "notebook", owner=OWNER, ip="1.1.1.1"))
        await idle(s.service)
        at_baseline(s.service, gate)


async def test_a_refused_turn_consumes_nothing():
    quotas = Quotas(Settings(_env_file=None, session_turns_per_minute=1))
    gate = TurnGate(parallel=1, queue=0, wait_s=5)
    caps = Caps(turns_in_flight_per_ip=1)
    async with serving(Script(), gate=gate, caps=caps, quotas=quotas) as s:
        g = await s.service.new_game(1, owner=OWNER, ip="1.1.1.1")
        with pytest.raises(ToolFailure):  # a stranger's turn on this game
            s.service.start_turn(g.game, "notebook", owner="stranger", ip="1.1.1.1")
        with pytest.raises(ApiError) as caught:  # a confirm with nothing pending
            s.service.start_confirm(g.game, "p-1", "yes", owner=OWNER, ip="1.1.1.1")
        assert caught.value.code == "no_such_pending"
        at_baseline(s.service, gate)
        s.service._quotas.turn(OWNER, "1.1.1.1")  # the one allowed hit is still there


async def test_a_refused_game_consumes_no_reservation():
    async with serving(Script(), caps=Caps(games_per_session=1, games_per_ip=5)) as s:
        await s.service.new_game(1, owner=OWNER, ip="1.1.1.1")
        with pytest.raises(ApiError):
            await s.service.new_game(2, owner=OWNER, ip="1.1.1.1")
        assert not s.service._reserved_by_owner and not s.service._reserved_by_ip


async def test_a_failed_creation_releases_its_reservation():
    async with serving(Script(), caps=Caps(games_per_session=1)) as s:
        with pytest.raises(ToolFailure):
            await s.service.new_game(1, "no-such-preset", owner=OWNER)
        assert not s.service._reserved_by_owner
        await s.service.new_game(1, owner=OWNER)


async def test_a_turn_waiting_behind_a_save_leaves_the_running_place_to_other_games(
    monkeypatch, tmp_path
):
    gate = TurnGate(parallel=1, queue=1, wait_s=5)
    script = Script().understand(intent="notebook").understand(intent="notebook")
    async with serving(script, gate=gate, saves_dir=tmp_path) as s:
        a = await s.service.new_game(1, owner="a")
        b = await s.service.new_game(2, owner="b")
        held = HeldSave(monkeypatch, s.service)
        saving = asyncio.create_task(s.service.save_game(a.game, owner="a"))
        await held.entered.wait()
        behind = asyncio.create_task(drain(s.service.start_turn(a.game, "notebook", owner="a")))
        events = await drain(s.service.start_turn(b.game, "notebook", owner="b"))
        assert "queued" not in kinds(events) and kinds(events)[-1] == "done"
        held.release.set()
        await saving
        assert kinds(await behind)[-1] == "done"
        await idle(s.service)
        at_baseline(s.service, gate)
