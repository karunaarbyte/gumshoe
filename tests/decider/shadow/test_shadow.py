import asyncio
import logging

import httpx
import pytest

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import (
    DeciderAllFailedError,
    DeciderConfigError,
    DeciderConnectionError,
    DeciderError,
)
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


async def test_unexpected_shadow_crash_does_not_affect_the_turn_and_is_recorded(result):
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    decider, recorder = make(FakeDecider("jev", result), shadow)
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    await decider.drain()
    [batch] = recorder.batches
    by_role = {r.role: r for r in batch}
    assert by_role["primary"].error is None and by_role["primary"].used
    assert by_role["shadow"].error == "[nimble] unexpected RuntimeError"


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


async def test_an_unexpected_primary_bug_falls_back_to_the_shadow_and_is_recorded(result):
    primary = FakeDecider("jev", error=RuntimeError("bug in primary"))
    decider, recorder = make(primary, FakeDecider("nimble", result))
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    [batch] = recorder.batches
    by_role = {r.role: r for r in batch}
    assert by_role["primary"].error == "[jev] unexpected RuntimeError"
    assert (by_role["shadow"].used, by_role["shadow"].fallback) == (True, True)


async def test_an_httpx_error_the_client_did_not_classify_still_falls_back(result):
    primary = FakeDecider("jev", error=httpx.DecodingError("bad gzip"))
    decider, recorder = make(primary, FakeDecider("nimble", result))
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    [batch] = recorder.batches
    assert {r.backend: r.error for r in batch} == {
        "jev": "[jev] unexpected DecodingError",
        "nimble": None,
    }


async def test_an_unexpected_primary_bug_with_no_shadow_is_a_decider_error():
    primary = FakeDecider("jev", error=RuntimeError("bug in primary"))
    decider, recorder = make(primary, None)
    with pytest.raises(DeciderError, match="unexpected RuntimeError") as info:
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert isinstance(info.value.__cause__, RuntimeError)
    [batch] = recorder.batches
    assert [(r.backend, r.used) for r in batch] == [("jev", False)]


async def test_aclose_waits_only_the_configured_grace_for_a_stuck_shadow(result):
    gate = asyncio.Event()  # the shadow never finishes
    shadow = FakeDecider("nimble", result, gate=gate)
    decider, recorder = make(FakeDecider("jev", result), shadow, drain_grace_s=0.05)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await asyncio.wait_for(decider.aclose(), 1)
    assert shadow.cancelled.is_set()
    assert [(r.backend, r.used) for r in recorder.batches[0]] == [("jev", True)]


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


async def test_two_crashing_backends_are_both_logged_and_end_in_all_failed(result, caplog):
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    primary = FakeDecider("jev", error=RuntimeError("bug in primary"), delay=0.05)
    decider, recorder = make(primary, shadow)
    with caplog.at_level(logging.ERROR), pytest.raises(DeciderAllFailedError):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    messages = [r.getMessage() for r in caplog.records]
    assert "shadow call crashed (nimble)" in messages
    assert "primary call crashed (jev)" in messages
    assert len(recorder.batches[0]) == 2


async def test_primary_failure_falls_back_to_the_shadow_and_flags_it(result):
    primary = FakeDecider("jev", error=DeciderConnectionError("jev", "timed out"))
    decider, recorder = make(primary, FakeDecider("nimble", result))
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="route") is result
    [batch] = recorder.batches  # recorded inline, no drain needed
    by_backend = {r.backend: r for r in batch}
    assert by_backend["nimble"].used is True and by_backend["jev"].used is False
    assert by_backend["jev"].fallback is True and by_backend["nimble"].fallback is True
    assert by_backend["jev"].error is not None and "timed out" in by_backend["jev"].error


async def test_missing_primary_key_also_falls_back(result):
    primary = FakeDecider("jev", error=DeciderConfigError("jev", "JEV_API_KEY is not set"))
    decider, recorder = make(primary, FakeDecider("nimble", result))
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    assert recorder.batches[0][0].fallback is True


async def test_both_failing_raises_all_failed_and_records_both():
    jev_err = DeciderConnectionError("jev", "timed out")
    nimble_err = DeciderConnectionError("nimble", "ollama is down")
    decider, recorder = make(
        FakeDecider("jev", error=jev_err), FakeDecider("nimble", error=nimble_err)
    )
    with pytest.raises(DeciderAllFailedError) as info:
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert set(info.value.failures) == {"jev", "nimble"}
    assert "timed out" in str(info.value) and "ollama is down" in str(info.value)
    assert info.value.__cause__ is jev_err
    [batch] = recorder.batches
    assert len(batch) == 2
    assert not any(r.used or r.fallback for r in batch)
    assert all(r.error is not None for r in batch)


async def test_primary_failure_without_a_shadow_reraises_the_original_error():
    err = DeciderConnectionError("jev", "timed out")
    decider, recorder = make(FakeDecider("jev", error=err), None)
    with pytest.raises(DeciderConnectionError) as info:
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert info.value is err
    assert len(recorder.batches[0]) == 1


async def test_recorder_failure_does_not_stop_the_fallback_result(result):
    primary = FakeDecider("jev", error=DeciderConnectionError("jev", "timed out"))
    decider, _ = make(
        primary, FakeDecider("nimble", result), FakeRecorder(error=OSError("db locked"))
    )
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result


async def test_fallback_waits_for_the_shadow_it_already_started(result):
    gate = asyncio.Event()
    primary = FakeDecider("jev", error=DeciderConnectionError("jev", "refused"))
    decider, recorder = make(primary, FakeDecider("nimble", result, gate=gate))
    turn = asyncio.create_task(decider.decide(DEMO_STATE, DEMO_QUESTIONS))
    await asyncio.sleep(0.05)
    assert not turn.done()  # the primary failed, but the turn waits for the shadow's answer
    gate.set()
    assert await asyncio.wait_for(turn, 1) is result


async def test_cancelling_during_a_fallback_cancels_the_shadow(result):
    gate = asyncio.Event()  # never set
    shadow = FakeDecider("nimble", result, gate=gate)
    primary = FakeDecider("jev", error=DeciderConnectionError("jev", "refused"))
    decider, _ = make(primary, shadow)
    turn = asyncio.create_task(decider.decide(DEMO_STATE, DEMO_QUESTIONS))
    await asyncio.sleep(0.05)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    await asyncio.wait_for(shadow.cancelled.wait(), 1)


async def test_primary_failure_plus_a_shadow_bug_is_all_failed_with_both_recorded(caplog):
    primary_err = DeciderConnectionError("jev", "timed out")
    shadow = FakeDecider("nimble", error=RuntimeError("bug in shadow"))
    decider, recorder = make(FakeDecider("jev", error=primary_err), shadow)
    with caplog.at_level(logging.ERROR), pytest.raises(DeciderAllFailedError) as info:
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert info.value.failures["jev"] is primary_err
    [batch] = recorder.batches
    assert {r.backend: (r.used, r.fallback) for r in batch} == {
        "jev": (False, False),
        "nimble": (False, False),
    }
    assert any("shadow call crashed" in r.getMessage() for r in caplog.records)


async def test_a_given_decision_id_is_on_every_record_of_that_decision(result, other_result):
    decider, recorder = make(FakeDecider("jev", other_result), FakeDecider("nimble", result))
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent", decision_id="abc123")
    await decider.drain()
    [batch] = recorder.batches
    assert {r.decision_id for r in batch} == {"abc123"}


async def test_without_a_decision_id_one_is_minted_and_shared(result, other_result):
    decider, recorder = make(FakeDecider("jev", other_result), FakeDecider("nimble", result))
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    await decider.drain()
    [batch] = recorder.batches
    ids = {r.decision_id for r in batch}
    assert len(ids) == 1 and ids != {"abc123"} and len(next(iter(ids))) == 32


async def test_a_given_decision_id_is_kept_when_the_primary_fails_and_the_shadow_answers(
    result,
):
    decider, recorder = make(
        FakeDecider("jev", error=DeciderConnectionError("jev", "down")),
        FakeDecider("nimble", result),
    )
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS, decision_id="fallback1") is result
    await decider.drain()
    assert {r.decision_id for batch in recorder.batches for r in batch} == {"fallback1"}
