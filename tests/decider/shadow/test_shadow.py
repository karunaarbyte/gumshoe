import asyncio
import logging

import pytest

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import DeciderConnectionError
from gumshoe.decider.contract.models import DecisionResult
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.decider.shadow.shadow import ShadowDecider
from tests.decider.fakes import FakeClock, FakeDecider, FakeRecorder


@pytest.fixture
def result(load_fixture):
    return DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))


@pytest.fixture
def other_result(load_fixture):
    return DecisionResult.model_validate(load_fixture("jev_all_types.response.json"))


def make(primary, shadow, recorder=None, **kwargs):
    recorder = recorder or FakeRecorder()
    return ShadowDecider(primary, shadow, recorder, **kwargs), recorder


async def test_is_a_decider_named_after_the_primary(result):
    decider, _ = make(FakeDecider("jev", result), FakeDecider("nimble", result))
    assert isinstance(decider, Decider)
    assert decider.name == "jev"


async def test_primary_only_when_there_is_no_shadow(result):
    decider, recorder = make(FakeDecider("jev", result), None)
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent") is result
    await decider.drain()
    [batch] = recorder.batches
    [record] = batch
    assert (record.backend, record.role, record.used, record.node) == (
        "jev",
        "primary",
        True,
        "intent",
    )


async def test_game_gets_the_primary_result_and_both_calls_are_recorded(result, other_result):
    decider, recorder = make(FakeDecider("jev", other_result), FakeDecider("nimble", result))
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent") is other_result
    await decider.drain()
    [batch] = recorder.batches
    primary, shadow = sorted(batch, key=lambda r: r.role == "shadow")
    assert (primary.backend, primary.used, primary.fallback) == ("jev", True, False)
    assert (shadow.backend, shadow.used, shadow.fallback) == ("nimble", False, False)
    assert primary.decision_id == shadow.decision_id
    assert primary.node == shadow.node == "intent"


async def test_turn_does_not_wait_for_a_slow_shadow(result):
    gate = asyncio.Event()  # the shadow cannot finish until we say so
    decider, recorder = make(FakeDecider("jev", result), FakeDecider("nimble", result, gate=gate))
    assert await asyncio.wait_for(decider.decide(DEMO_STATE, DEMO_QUESTIONS), timeout=1) is result
    assert recorder.batches == []  # shadow still blocked, nothing recorded yet
    gate.set()
    await decider.drain()
    assert len(recorder.batches[0]) == 2


async def test_shadow_error_is_recorded_not_raised(result):
    shadow = FakeDecider("nimble", error=DeciderConnectionError("nimble", "ollama is down"))
    decider, recorder = make(FakeDecider("jev", result), shadow)
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    await decider.drain()
    by_role = {r.role: r for r in recorder.batches[0]}
    assert by_role["shadow"].error is not None and "ollama is down" in by_role["shadow"].error
    assert by_role["shadow"].answers is None
    assert by_role["primary"].error is None and by_role["primary"].used


async def test_unexpected_shadow_crash_does_not_affect_the_turn(result):
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    decider, recorder = make(FakeDecider("jev", result), shadow)
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    await decider.drain()
    [batch] = recorder.batches
    assert [r.backend for r in batch] == ["jev"]  # primary still recorded


async def test_recorder_failure_does_not_fail_the_turn(result):
    decider, _ = make(
        FakeDecider("jev", result),
        FakeDecider("nimble", result),
        FakeRecorder(error=OSError("db locked")),
    )
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    await decider.drain()  # must not raise either


async def test_cancelling_a_turn_cancels_the_shadow_call(result):
    primary = FakeDecider("jev", result, delay=10)
    shadow = FakeDecider("nimble", result, delay=10)
    decider, _ = make(primary, shadow)
    turn = asyncio.create_task(decider.decide(DEMO_STATE, DEMO_QUESTIONS))
    await asyncio.sleep(0.05)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    await asyncio.wait_for(asyncio.gather(primary.cancelled.wait(), shadow.cancelled.wait()), 1)


async def test_unexpected_primary_bug_cancels_the_shadow_and_propagates(result):
    primary = FakeDecider("jev", error=RuntimeError("bug in primary"))
    shadow = FakeDecider("nimble", result, delay=10)
    decider, recorder = make(primary, shadow)
    with pytest.raises(RuntimeError, match="bug in primary"):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await asyncio.wait_for(shadow.cancelled.wait(), 1)
    assert recorder.batches == []


async def test_aclose_waits_for_recording_then_closes_both(result):
    primary, shadow = FakeDecider("jev", result), FakeDecider("nimble", result, delay=0.1)
    decider, recorder = make(primary, shadow)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await decider.aclose()
    assert len(recorder.batches) == 1 and len(recorder.batches[0]) == 2
    assert primary.closed and shadow.closed


async def test_first_call_is_cold_then_warm_then_cold_after_idle(result):
    clock = FakeClock()
    decider, recorder = make(
        FakeDecider("jev", result), FakeDecider("nimble", result), cold_after_s=300, clock=clock
    )

    async def cold_flags():
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
        await decider.drain()
        return {r.backend: r.cold for r in recorder.batches[-1]}

    assert await cold_flags() == {"jev": True, "nimble": True}  # nothing seen yet
    clock.advance(10)
    assert await cold_flags() == {"jev": False, "nimble": False}
    clock.advance(301)
    assert await cold_flags() == {"jev": True, "nimble": True}  # idle longer than cold_after_s


async def test_same_backend_twice_is_rejected(result):
    with pytest.raises(ValueError, match="differ"):
        ShadowDecider(FakeDecider("jev", result), FakeDecider("jev", result), FakeRecorder())


async def test_latency_and_timestamp_are_recorded(result):
    decider, recorder = make(FakeDecider("jev", result, delay=0.05), None)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await decider.drain()
    [record] = recorder.batches[0]
    assert record.latency_ms >= 45
    assert record.ts.endswith("+00:00") and "T" in record.ts


async def test_drain_timeout_still_records_the_primary(result):
    gate = asyncio.Event()  # the shadow never finishes
    shadow = FakeDecider("nimble", result, gate=gate)
    decider, recorder = make(FakeDecider("jev", result), shadow)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await decider.drain(grace_s=0.05)
    assert shadow.cancelled.is_set()  # drain waited for the cancellation to finish
    [batch] = recorder.batches
    assert [(r.backend, r.used) for r in batch] == [("jev", True)]


async def test_a_crashing_shadow_is_logged_exactly_once(result, caplog):
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    decider, _ = make(FakeDecider("jev", result), shadow)
    with caplog.at_level(logging.ERROR):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
        await decider.drain()
    crashes = [r for r in caplog.records if "shadow call crashed" in r.getMessage()]
    assert len(crashes) == 1


async def test_a_shadow_crash_is_logged_even_when_the_primary_blows_up_first(result, caplog):
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    primary = FakeDecider("jev", error=RuntimeError("bug in primary"), delay=0.05)
    decider, _ = make(primary, shadow)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="bug in primary"):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert any("shadow call crashed" in r.getMessage() for r in caplog.records)
