"""An omniscient player. It knows the truth and drives the real play functions, so any
disagreement with the validator is a bug in one of the two (they share only the gate spec).

It never imports gumshoe.cases.validate: the two must stay independent implementations."""

from collections import deque
from dataclasses import dataclass

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.types import Held
from gumshoe.cases.play.accuse import AccuseKind, accuse
from gumshoe.cases.play.engine import all_sources, gather, use_source
from gumshoe.cases.play.state import PlayState, Triple, new_state
from gumshoe.cases.rules import gate


class SearchLimitExceeded(Exception):
    """min_sources visited more states than the node limit allows."""


def read_everything(ix: CaseIndex, state: PlayState | None = None) -> PlayState:
    """Use every source, over and over, until nothing new turns up."""
    state = state if state is not None else new_state(ix.case)
    sources = all_sources(ix)
    while True:
        before = state
        for source in sources:
            state, _ = use_source(ix, state, source)
        if state == before:
            return state


def _truthful(ix: CaseIndex, held: Held) -> Held:
    return frozenset(f for f in held if f in ix.facts and ix.facts[f].truthful)


def ruled_out(ix: CaseIndex, held: Held, axis: Axis) -> frozenset[str]:
    """Candidates on this axis ruled out by a truthful held fact (lies are ignored)."""
    return frozenset(
        e.candidate
        for f in _truthful(ix, held)
        for e in ix.facts[f].effects
        if e.axis is axis and e.kind is EffectKind.RULES_OUT
    )


def survivors(ix: CaseIndex, held: Held, axis: Axis) -> frozenset[str]:
    return frozenset(ix.candidates[axis]) - ruled_out(ix, held, axis)


def _proven(ix: CaseIndex, held: Held, axis: Axis) -> bool:
    truth = ix.truth(axis)
    return any(
        e.axis is axis and e.candidate == truth and e.kind is EffectKind.PROVES
        for f in _truthful(ix, held)
        for e in ix.facts[f].effects
    )


def axis_decidable(ix: CaseIndex, held: Held, axis: Axis) -> bool:
    """Can the truth on this axis be settled from truthful holdings, and named under the gate?"""
    truth = ix.truth(axis)
    if truth in ruled_out(ix, held, axis):
        return False
    if not (_proven(ix, held, axis) or survivors(ix, held, axis) == frozenset({truth})):
        return False
    return gate.permission(ix, _truthful(ix, held), axis, truth).allowed


@dataclass(frozen=True)
class Verdict:
    reach: frozenset[str]  # facts held after reading everything
    single_survivor: bool  # truthful rule-outs leave exactly the truth on every axis
    decidable_axes: tuple[Axis, ...]
    can_win: bool  # reading everything, then naming the truth with confirmation, wins


def judge(case: Case) -> Verdict:
    ix = CaseIndex.of(case)
    state = read_everything(ix)
    held = state.held
    try:
        truth = Triple(who=case.truth.who, how=case.truth.how, why=case.truth.why)
        _, result = accuse(ix, state, truth, confirmed=True)
        can_win = result.kind is AccuseKind.RESOLVED and result.correct == len(Axis)
    except ValueError:  # a garbled case whose truth is not among its candidates
        can_win = False
    return Verdict(
        reach=held,
        single_survivor=all(
            survivors(ix, held, axis) == frozenset({ix.truth(axis)}) for axis in Axis
        ),
        decidable_axes=tuple(axis for axis in Axis if axis_decidable(ix, held, axis)),
        can_win=can_win,
    )


def spof_axes(case: Case, fact_id: str) -> frozenset[Axis]:
    """Axes that can no longer be decided once this (non-start) fact is gone from the case."""
    smaller = case.model_copy(update={"facts": tuple(f for f in case.facts if f.id != fact_id)})
    ix = CaseIndex.of(smaller)
    held = read_everything(ix).held
    return frozenset(axis for axis in Axis if not axis_decidable(ix, held, axis))


def min_sources(case: Case, *, node_limit: int = 20_000) -> int | None:
    """Fewest source uses after which every axis is decidable; None if no play gets there.

    Decidability is not monotone in the held set: a truthful rule-out of the truth found later
    undoes an early "decided", and the player cannot avoid finding it. So a case that is not
    decidable once everything is read has no winning play at all."""
    ix = CaseIndex.of(case)
    full = read_everything(ix).held
    if not all(axis_decidable(ix, full, axis) for axis in Axis):
        return None
    sources = all_sources(ix)
    # the BFS steps with engine.gather (the held set use_source would reach, without its
    # contradiction and lead work); read_everything above keeps the full use_source path
    start = new_state(case).held
    seen = {start}
    queue: deque[tuple[Held, int]] = deque([(start, 0)])
    while queue:
        held, depth = queue.popleft()
        if all(axis_decidable(ix, held, axis) for axis in Axis):
            return depth
        for source in sources:
            nxt = gather(ix, held, source)
            if nxt not in seen:
                if len(seen) >= node_limit:
                    raise SearchLimitExceeded(node_limit)
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    return None
