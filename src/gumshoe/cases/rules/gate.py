"""The accusation gate: depends only on what is held and on visible exposure, never on truth.

permission(X) = lead(X) OR every other candidate on the axis has a held rule-out
warn(X)       = X itself has a held rule-out (the same soft warning for a true fact or a lie)
A held rule-out is a held `rules_out` fact that is not an exposed lie; a lie is exposed only
when both the lie and one of its exposers are held.
"""

from dataclasses import dataclass

from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.types import Held


@dataclass(frozen=True)
class Permission:
    allowed: bool
    warn: bool


def exposed(index: CaseIndex, held: Held) -> frozenset[str]:
    return frozenset(
        f.id
        for f in index.case.facts
        if not f.truthful and f.id in held and any(e in held for e in f.exposed_by)
    )


def _has_effect(
    index: CaseIndex,
    held: Held,
    axis: Axis,
    candidate: str,
    kinds: tuple[EffectKind, ...],
    skip: frozenset[str],
) -> bool:
    return any(
        f.id in held
        and f.id not in skip
        and any(e.axis is axis and e.candidate == candidate and e.kind in kinds for e in f.effects)
        for f in index.case.facts
    )


def lead(index: CaseIndex, held: Held, axis: Axis, candidate: str) -> bool:
    """Any held supports/proves fact on the candidate, lie-sourced or not."""
    return _has_effect(
        index, held, axis, candidate, (EffectKind.SUPPORTS, EffectKind.PROVES), frozenset()
    )


def permission(index: CaseIndex, held: Held, axis: Axis, candidate: str) -> Permission:
    skip = exposed(index, held)
    others = [c for c in index.candidates[axis] if c != candidate]
    eliminated = bool(others) and all(
        _has_effect(index, held, axis, c, (EffectKind.RULES_OUT,), skip) for c in others
    )
    own = _has_effect(index, held, axis, candidate, (EffectKind.RULES_OUT,), skip)
    return Permission(allowed=lead(index, held, axis, candidate) or eliminated, warn=own)
