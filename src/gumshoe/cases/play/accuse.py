"""The accusation flow: gate check, repeat rule, confirmation, count-only scoring."""

from dataclasses import dataclass
from enum import StrEnum

from gumshoe.cases.model.entities import Truth
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.state import (
    MAX_ATTEMPTS,
    AccusationRecord,
    PlayState,
    Status,
    Triple,
)
from gumshoe.cases.rules import gate


class AccuseKind(StrEnum):
    GAME_OVER = "game_over"
    NOT_PERMITTED = "not_permitted"
    REPEAT = "repeat"
    NEEDS_CONFIRMATION = "needs_confirmation"
    RESOLVED = "resolved"


class GameNotOver(Exception):
    """The truth is revealed only once the game has ended."""


@dataclass(frozen=True)
class Check:
    blocked: tuple[Axis, ...]  # parts the gate does not yet allow
    # allowed parts the player holds a rule-out against
    warned: tuple[Axis, ...]
    repeat: bool  # the identical triple was already tried


@dataclass(frozen=True)
class AccuseResult:
    kind: AccuseKind
    check: Check | None = None
    correct: int | None = None


def check_accusation(ix: CaseIndex, state: PlayState, triple: Triple) -> Check:
    held = state.held
    blocked: list[Axis] = []
    warned: list[Axis] = []
    for axis in Axis:
        candidate = triple.on(axis)
        if candidate not in ix.candidates[axis]:
            msg = f"{candidate!r} is not a candidate on the {axis.value} axis"
            raise ValueError(msg)
        permission = gate.permission(ix, held, axis, candidate)
        if not permission.allowed:
            blocked.append(axis)
        elif permission.warn:
            warned.append(axis)
    repeat = any(record.triple == triple for record in state.accusations)
    return Check(blocked=tuple(blocked), warned=tuple(warned), repeat=repeat)


def score(ix: CaseIndex, triple: Triple) -> int:
    return sum(1 for axis in Axis if triple.on(axis) == ix.truth(axis))


def accuse(
    ix: CaseIndex, state: PlayState, triple: Triple, *, confirmed: bool = False
) -> tuple[PlayState, AccuseResult]:
    """Rechecks permission and the repeat rule at call time; only a confirmed,
    permitted, new triple consumes an attempt. Feedback is the count of
    correct parts and nothing else."""
    if state.status is not Status.PLAYING:
        return state, AccuseResult(AccuseKind.GAME_OVER)
    check = check_accusation(ix, state, triple)
    if check.blocked:
        return state, AccuseResult(AccuseKind.NOT_PERMITTED, check)
    if check.repeat:
        return state, AccuseResult(AccuseKind.REPEAT, check)
    if not confirmed:
        return state, AccuseResult(AccuseKind.NEEDS_CONFIRMATION, check)
    correct = score(ix, triple)
    attempts = state.attempts + 1
    if correct == len(Axis):
        status = Status.WON
    elif attempts >= MAX_ATTEMPTS:
        status = Status.LOST
    else:
        status = Status.PLAYING
    after = state.model_copy(
        update={
            "attempts": attempts,
            "accusations": (
                *state.accusations,
                AccusationRecord(triple=triple, correct=correct),
            ),
            "status": status,
        }
    )
    return after, AccuseResult(AccuseKind.RESOLVED, check, correct)


def give_up(state: PlayState) -> PlayState:
    if state.status is not Status.PLAYING:
        return state
    return state.model_copy(update={"status": Status.LOST})


def reveal(ix: CaseIndex, state: PlayState) -> Truth:
    if state.status is Status.PLAYING:
        raise GameNotOver("the case is still open")
    return ix.case.truth
