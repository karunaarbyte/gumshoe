"""Immutable play state: what the player holds, what is spent, how the game stands."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, field_validator

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Frozen
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.serialize import skeleton_digest
from gumshoe.cases.model.types import Held

MAX_ATTEMPTS = 3


class Status(StrEnum):
    PLAYING = "playing"
    WON = "won"
    LOST = "lost"


class Triple(Frozen):
    """An accusation in candidate ids: who did it, how, and why."""

    who: str
    how: str
    why: str

    def on(self, axis: Axis) -> str:
        return {Axis.WHO: self.who, Axis.HOW: self.how, Axis.WHY: self.why}[axis]


class AccusationRecord(Frozen):
    triple: Triple
    correct: int


class PlayState(Frozen):
    case_digest: str
    discovered: tuple[str, ...] = ()
    attempts: int = Field(default=0, ge=0, le=3)
    accusations: tuple[AccusationRecord, ...] = ()
    status: Status = Status.PLAYING

    @field_validator("discovered", mode="after")
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @property
    def held(self) -> Held:
        return frozenset(self.discovered)

    def with_facts(self, fact_ids: Iterable[str]) -> "PlayState":
        merged = tuple(sorted(set(self.discovered) | set(fact_ids)))
        return self.model_copy(update={"discovered": merged})


def new_state(case: Case) -> PlayState:
    ids = {f.id for f in case.facts}
    return PlayState(
        case_digest=skeleton_digest(case),
        discovered=tuple(f for f in case.start.facts if f in ids),
    )
