"""The confirm step for irreversible actions (accuse, give up) as a pure state machine."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.understand import Intent

NOT_ACTIONABLE = frozenset({"other", "meta"})
EPSILON = 1e-9  # 1 - 0.8 is 0.19999999999999996 in floats; both bands are inclusive


@dataclass
class Pending:
    kind: Literal["accuse", "give_up"]
    line: str  # the confirmation text the player was shown
    handles: tuple[str, str, str] | None = None  # who, how, why (accuse only)
    reasked: bool = False


class Step(Enum):
    PROCESS = "process"  # nothing pending: handle the intent normally
    RUN = "run"  # confirmed: run the pending action
    CANCEL = "cancel"  # a no: drop it, say so
    CANCEL_PROCESS = "cancel_process"  # a no with a real new intent: cancel, then handle it
    DROP_PROCESS = "drop_process"  # unsure, but a real new intent: forget the pending action
    REASK = "reask"  # unsure: ask once more
    CLEAR_PROCESS = "clear_process"  # unsure again: forget it and handle the turn normally


def is_actionable(intent: Intent, config: AgentConfig) -> bool:
    return intent.intent_confidence >= config.confidence_gate and intent.name not in NOT_ACTIONABLE


def resolve_pending(pending: Pending | None, intent: Intent, config: AgentConfig) -> Step:
    if pending is None:
        return Step.PROCESS
    p_yes = 0.5 if intent.confirms_pending is None else intent.confirms_pending
    actionable = is_actionable(intent, config)
    # a "yes" next to a different irreversible request must not run the pending one
    new_action = actionable and (
        intent.name == "accuse" or (intent.name == "give_up" and pending.kind != "give_up")
    )
    if p_yes >= config.confirm_gate - EPSILON and not new_action:
        return Step.RUN
    if p_yes <= 1 - config.confirm_gate + EPSILON:
        return Step.CANCEL_PROCESS if actionable else Step.CANCEL
    if actionable:
        return Step.DROP_PROCESS
    return Step.CLEAR_PROCESS if pending.reasked else Step.REASK
