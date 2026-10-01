"""What is recorded for each backend call, and the interface that stores it."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from gumshoe.decider.contract.answers import answer_confidence
from gumshoe.decider.contract.errors import DeciderError
from gumshoe.decider.contract.models import Answer, DecisionResult

Role = Literal["primary", "shadow"]
PREVIEW_CHARS = 200


@dataclass(frozen=True)
class CallOutcome:
    """One finished backend call, before we know whether the game used it."""

    backend: str
    role: Role
    ts: str  # ISO-8601 UTC, microsecond precision
    cold: bool
    latency_ms: float
    result: DecisionResult | None = None
    failure: DeciderError | None = None

    @property
    def error(self) -> str | None:
        return None if self.failure is None else str(self.failure)


@dataclass(frozen=True)
class CallRecord:
    """One row of the stats store."""

    decision_id: str
    node: str
    backend: str
    role: Role
    used: bool  # the game used this call's result
    fallback: bool  # this decision's used result came from the shadow because the primary failed
    cold: bool
    ts: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    mean_confidence: float | None
    min_confidence: float | None
    error: str | None
    state_preview: str
    answers: dict[str, Answer] | None


class Recorder(Protocol):
    async def record(self, records: Sequence[CallRecord]) -> None: ...


def build_record(
    *, decision_id: str, node: str, state: str, call: CallOutcome, used: bool, fallback: bool
) -> CallRecord:
    result = call.result
    confidences = [answer_confidence(a) for a in result.answers.values()] if result else []
    usage = result.usage if result else None
    return CallRecord(
        decision_id=decision_id,
        node=node,
        backend=call.backend,
        role=call.role,
        used=used,
        fallback=fallback,
        cold=call.cold,
        ts=call.ts,
        latency_ms=call.latency_ms,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        mean_confidence=sum(confidences) / len(confidences) if confidences else None,
        min_confidence=min(confidences) if confidences else None,
        error=call.error,
        state_preview=state[:PREVIEW_CHARS],
        answers=dict(result.answers) if result else None,
    )
