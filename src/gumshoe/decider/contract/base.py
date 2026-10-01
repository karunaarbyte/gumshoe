"""The interface every decision backend (and wrapper) satisfies."""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from gumshoe.decider.contract.models import DecisionResult, Question


@runtime_checkable
class Decider(Protocol):
    name: str

    async def decide(
        self, state: str, questions: Mapping[str, Question], *, node: str = "adhoc"
    ) -> DecisionResult: ...

    async def aclose(self) -> None: ...
