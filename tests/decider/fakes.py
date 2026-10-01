import asyncio
from collections.abc import Mapping

from gumshoe.decider.contract.errors import DeciderError
from gumshoe.decider.contract.models import DecisionResult, Question


class FakeDecider:
    """A Decider that returns a canned result (or raises a canned error)."""

    def __init__(
        self,
        name: str,
        result: DecisionResult | None = None,
        error: DeciderError | None = None,
        delay: float = 0.0,
    ) -> None:
        self.name = name
        self._result = result
        self._error = error
        self._delay = delay
        self.closed = False
        self.nodes: list[str] = []  # node labels of every call, for assertions

    async def decide(
        self, state: str, questions: Mapping[str, Question], *, node: str = "adhoc"
    ) -> DecisionResult:
        self.nodes.append(node)
        await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    async def aclose(self) -> None:
        self.closed = True
