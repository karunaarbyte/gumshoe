"""Immutable play state: what the player holds, what is spent, how the game stands."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

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
    attempts: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    accusations: tuple[AccusationRecord, ...] = ()
    status: Status = Status.PLAYING

    @field_validator("discovered", mode="after")
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _consistent(self) -> "PlayState":
        """A save must be a state the accusation flow can produce (a hand-edited one may not)."""
        if self.attempts != len(self.accusations):
            raise ValueError("attempts must equal the number of accusations")
        if self.status is Status.PLAYING and self.attempts >= MAX_ATTEMPTS:
            raise ValueError("a game still playing must have an attempt left")
        winners = [i for i, a in enumerate(self.accusations) if a.correct == len(Axis)]
        if self.status is Status.WON and winners != [len(self.accusations) - 1]:
            raise ValueError("a won game ends with its one fully correct accusation")
        if self.status is not Status.WON and winners:
            raise ValueError("a fully correct accusation wins the game")
        return self

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
