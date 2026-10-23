"""What the budget needs to know about a call, kept free of any storage or HTTP."""

from collections.abc import Mapping
from contextvars import ContextVar
from typing import Protocol, runtime_checkable

from gumshoe.decider.contract.models import Question

# Who a decision is for (a client IP key), set by the API for the length of a turn. A ContextVar
# because the decider interface has no place for it and every task inherits its creator's value.
client_key: ContextVar[str] = ContextVar("client_key", default="")


@runtime_checkable
class UsageLedger(Protocol):
    def add_usage(self, day: str, key: str, tokens: int) -> None: ...

    def usage_totals(self, day: str) -> dict[str, int]: ...


def estimate_tokens(state: str, questions: Mapping[str, Question]) -> int:
    """A rough size of a request in tokens (about three characters each), for a call that
    failed and so reported no usage. Never zero: a failed call may still have been billed."""
    chars = len(state) + sum(len(q.model_dump_json()) for q in questions.values())
    return max(1, chars // 3)
