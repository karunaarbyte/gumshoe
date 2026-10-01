"""Run the same request against several deciders concurrently."""

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import DeciderError
from gumshoe.decider.contract.models import DecisionResult, Question


@dataclass
class Outcome:
    result: DecisionResult | None = None
    error: str | None = None
    latency_ms: float | None = None


async def run_one(
    decider: Decider, state: str, questions: Mapping[str, Question], node: str = "compare"
) -> Outcome:
    started = time.perf_counter()
    try:
        result = await decider.decide(state, questions, node=node)
    except DeciderError as exc:
        return Outcome(error=str(exc), latency_ms=(time.perf_counter() - started) * 1000)
    return Outcome(result=result, latency_ms=(time.perf_counter() - started) * 1000)


async def compare_backends(
    deciders: Mapping[str, Decider],
    state: str,
    questions: Mapping[str, Question],
    node: str = "compare",
) -> dict[str, Outcome]:
    names = list(deciders)
    outcomes = await asyncio.gather(
        *(run_one(deciders[name], state, questions, node) for name in names)
    )
    return dict(zip(names, outcomes))
