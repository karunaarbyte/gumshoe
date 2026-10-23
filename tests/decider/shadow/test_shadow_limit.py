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


class _FailsFromTheSecondCall(FakeDecider):
    async def decide(self, state, questions, *, node="adhoc", decision_id=None):
        self.nodes.append(node)
        if len(self.nodes) >= 2:
            raise DeciderError("jev", "down")
        return self._result


class _GatedOnlyFirst(FakeDecider):
    """A shadow whose first call blocks on the gate; later calls answer (or fail) at once."""

    async def decide(self, state, questions, *, node="adhoc", decision_id=None):
        self.nodes.append(node)
        if len(self.nodes) == 1:
            assert self._gate is not None
            await self._gate.wait()
        if self._error is not None and len(self.nodes) > 1:
            raise self._error
        return self._result


async def test_a_failing_primary_with_a_skipped_shadow_falls_back_inline(result):
    release = asyncio.Event()
    shadow = _GatedOnlyFirst("nimble", result, gate=release)
    recorder = FakeRecorder()
    decider = ShadowDecider(
        _FailsFromTheSecondCall("jev", result), shadow, recorder, shadow_parallel=1
    )
    # succeeds; its shadow now holds the one place
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    await asyncio.sleep(0)
    # the primary fails, the parallel shadow was skipped: the shadow answers inline instead
    answer = await asyncio.wait_for(
        decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent", decision_id="d2"), 5
    )
    assert answer == result
    assert len(shadow.nodes) == 2
    assert decider.shadow_skipped == 0  # the shadow did run for that decision, as the fallback
    release.set()
    await decider.drain()
    rows = [r for batch in recorder.batches for r in batch if r.decision_id == "d2"]
    by_role = {r.role: r for r in rows}
    assert set(by_role) == {"primary", "shadow"}  # the primary failure is still recorded
    assert by_role["shadow"].used and by_role["shadow"].fallback
    assert not by_role["primary"].used


async def test_a_failing_primary_and_a_failing_inline_fallback_surface_an_error(result):
    release = asyncio.Event()
    shadow = _GatedOnlyFirst("nimble", result, error=DeciderError("nimble", "down"), gate=release)
    decider = ShadowDecider(
        _FailsFromTheSecondCall("jev", result), shadow, FakeRecorder(), shadow_parallel=1
    )
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")
    await asyncio.sleep(0)
    with pytest.raises(DeciderError):
        await asyncio.wait_for(decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent"), 5)
    assert len(shadow.nodes) == 2
    release.set()
    await decider.drain()


async def test_a_failing_primary_without_any_shadow_surfaces_its_error():
    decider = ShadowDecider(
        FakeDecider("jev", error=DeciderError("jev", "down")), None, FakeRecorder()
    )
    with pytest.raises(DeciderError):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent")


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
