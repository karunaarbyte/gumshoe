import asyncio
from collections.abc import Mapping, Sequence

from gumshoe.decider.contract.models import DecisionResult, Question
from gumshoe.decider.shadow.records import CallRecord


class FakeDecider:
    """A Decider that returns a canned result (or raises a canned error)."""

    def __init__(
        self,
        name: str,
        result: DecisionResult | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.name = name
        self._result = result
        self._error = error
        self._delay = delay
        self._gate = gate  # if given, a call blocks until the test sets it
        self.closed = False
        self.cancelled = asyncio.Event()  # set when a call is cancelled mid-flight
        self.nodes: list[str] = []  # node labels of every call, for assertions
        self.decision_ids: list[str | None] = []

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        self.nodes.append(node)
        self.decision_ids.append(decision_id)
        try:
            await asyncio.sleep(self._delay)
            if self._gate is not None:
                await self._gate.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    async def aclose(self) -> None:
        self.closed = True


class FakeRecorder:
    """A Recorder that keeps every batch in memory, or fails on demand."""

    def __init__(self, error: Exception | None = None) -> None:
        self.batches: list[list[CallRecord]] = []
        self._error = error

    async def record(self, records: Sequence[CallRecord]) -> None:
        if self._error is not None:
            raise self._error
        self.batches.append(list(records))


class FakeClock:
    """A controllable replacement for time.monotonic."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
