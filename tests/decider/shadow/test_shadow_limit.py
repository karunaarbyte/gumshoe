import asyncio

import pytest

from gumshoe.decider.contract.errors import DeciderError
from gumshoe.decider.contract.models import DecisionResult
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.decider.shadow.shadow import ShadowDecider
from tests.decider.fakes import FakeDecider, FakeRecorder


@pytest.fixture
def result(load_fixture):
    return DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))


async def test_a_shadow_call_is_skipped_not_queued_when_the_limit_is_reached(result):
    release = asyncio.Event()
    primary = FakeDecider("jev", result)
    shadow = FakeDecider("nimble", result, gate=release)
    recorder = FakeRecorder()
    decider = ShadowDecider(primary, shadow, recorder, shadow_parallel=1)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")  # the shadow is now running
    await asyncio.sleep(0)
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")  # at the limit: skipped
    assert decider.shadow_skipped == 1
    assert len(shadow.nodes) == 1  # the second decision never called the shadow
    release.set()
    await decider.drain()
    rows = [r for batch in recorder.batches for r in batch]
    shadow_rows = [r for r in rows if r.role == "shadow"]
    assert len(shadow_rows) == 1  # no shadow row for the skipped decision
    assert len([r for r in rows if r.role == "primary"]) == 2


async def test_the_place_is_freed_when_the_shadow_finishes(result):
    decider = ShadowDecider(
        FakeDecider("jev", result),
        FakeDecider("nimble", result),
        FakeRecorder(),
        shadow_parallel=1,
    )
    for _ in range(3):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
        await decider.drain()
    assert decider.shadow_skipped == 0


async def test_zero_means_no_limit(result):
    release = asyncio.Event()
    shadow = FakeDecider("nimble", result, gate=release)
    decider = ShadowDecider(FakeDecider("jev", result), shadow, FakeRecorder(), shadow_parallel=0)
    for _ in range(5):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    await asyncio.sleep(0)
    assert len(shadow.nodes) == 5 and decider.shadow_skipped == 0
    release.set()
    await decider.drain()


async def test_a_failing_primary_with_a_skipped_shadow_surfaces_its_error(result):
    class FailsFromTheSecondCall(FakeDecider):
        async def decide(self, state, questions, *, node="adhoc", decision_id=None):
            self.nodes.append(node)
            if len(self.nodes) >= 2:
                raise DeciderError("jev", "down")
            return result

    release = asyncio.Event()
    busy_shadow = FakeDecider("nimble", result, gate=release)
    decider = ShadowDecider(
        FailsFromTheSecondCall("jev"), busy_shadow, FakeRecorder(), shadow_parallel=1
    )
    # succeeds; its shadow now holds the one place
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    await asyncio.sleep(0)
    with pytest.raises(DeciderError):
        # skipped shadow: no fallback
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    assert decider.shadow_skipped == 1
    release.set()
    await decider.drain()


async def test_the_place_is_freed_when_the_shadow_raises(result):
    decider = ShadowDecider(
        FakeDecider("jev", result),
        FakeDecider("nimble", error=DeciderError("nimble", "down")),
        FakeRecorder(),
        shadow_parallel=1,
    )
    for _ in range(3):
        await asyncio.wait_for(decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent"), 5)
        await asyncio.wait_for(decider.drain(), 5)
    assert decider.shadow_skipped == 0


async def test_the_place_is_freed_when_the_primary_is_cancelled(result):
    primary_gate = asyncio.Event()
    shadow_gate = asyncio.Event()
    primary = FakeDecider("jev", result, gate=primary_gate)
    shadow = FakeDecider("nimble", result, gate=shadow_gate)
    decider = ShadowDecider(primary, shadow, FakeRecorder(), shadow_parallel=1)
    first = asyncio.create_task(decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent"))
    await asyncio.sleep(0)  # both calls start; the shadow holds the one place
    await asyncio.sleep(0)
    assert primary.nodes and shadow.nodes
    first.cancel()
    await asyncio.wait_for(shadow.cancelled.wait(), 5)  # the shadow was cancelled with the primary
    await asyncio.sleep(0)  # let its done callback run
    primary_gate.set()
    shadow_gate.set()
    await asyncio.wait_for(decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent"), 5)
    await asyncio.wait_for(decider.drain(), 5)
    assert decider.shadow_skipped == 0
