"""Using sources: what a player can open, find and learn. Pure functions over (index, state)."""

from dataclasses import dataclass
from enum import StrEnum

from gumshoe.cases.model.entities import Fact, SourceRef
from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.types import Held
from gumshoe.cases.play.state import PlayState
from gumshoe.cases.rules import gate


class SourceStatus(StrEnum):
    OK = "ok"
    NOTHING_NEW = "nothing_new"
    LOCKED = "locked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Contradiction:
    lie: str
    exposer: str


@dataclass(frozen=True)
class Outcome:
    status: SourceStatus
    new_facts: tuple[str, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    opened: tuple[SourceRef, ...] = ()


def source_sort_key(source: SourceRef) -> tuple[str, str, str]:
    return (source.kind.value, source.target, source.subject or "")


def all_sources(ix: CaseIndex) -> tuple[SourceRef, ...]:
    """Every source the case holds facts at, in a neutral order."""
    return tuple(sorted({f.source for f in ix.case.facts}, key=source_sort_key))


def record_kinds(ix: CaseIndex) -> tuple[str, ...]:
    return tuple(sorted({r.kind for r in ix.case.record_sources}))


def _exists(ix: CaseIndex, source: SourceRef) -> bool:
    if source.kind is SourceKind.SEARCH:
        return source.target in ix.locations
    if source.kind is SourceKind.INTERROGATE:
        return source.target in ix.suspects
    subject = source.subject or ""
    return source.target in record_kinds(ix) and (
        subject in ix.suspects or subject in ix.locations or subject in ix.events
    )


def is_open(ix: CaseIndex, held: Held, source: SourceRef) -> bool:
    """Can the player use this source right now? (start access or a fully held gate)"""
    case = ix.case
    if source.kind is SourceKind.SEARCH:
        loc = ix.locations.get(source.target)
        return loc is not None and (
            loc.id in case.start.locations
            or (bool(loc.requires) and all(r in held for r in loc.requires))
        )
    if source.kind is SourceKind.INTERROGATE:
        sus = ix.suspects.get(source.target)
        return sus is not None and (
            sus.id in case.start.suspects
            or (bool(sus.requires) and all(r in held for r in sus.requires))
        )
    rs = ix.record_sources.get((source.target, source.subject or ""))
    return rs is not None and all(r in held for r in rs.requires)


def available_facts(ix: CaseIndex, held: Held, source: SourceRef) -> tuple[Fact, ...]:
    """Facts at this source that the player does not hold and whose `requires` are held."""
    if not is_open(ix, held, source):
        return ()
    return tuple(
        f for f in ix.facts_at(source) if f.id not in held and all(r in held for r in f.requires)
    )


def source_status(ix: CaseIndex, held: Held, source: SourceRef) -> SourceStatus:
    if not _exists(ix, source):
        return SourceStatus.UNKNOWN
    if source.kind is SourceKind.RECORD and (
        (source.target, source.subject or "") not in ix.record_sources
    ):
        return SourceStatus.NOTHING_NEW  # a valid kind and subject with no declared pair
    if not is_open(ix, held, source):
        return SourceStatus.LOCKED
    return SourceStatus.OK if available_facts(ix, held, source) else SourceStatus.NOTHING_NEW


def use_source(ix: CaseIndex, state: PlayState, source: SourceRef) -> tuple[PlayState, Outcome]:
    """Use a source: returns ALL newly available facts. Idempotent; facts only accumulate."""
    held = state.held
    status = source_status(ix, held, source)
    if status is not SourceStatus.OK:
        return state, Outcome(status)
    new = tuple(f.id for f in available_facts(ix, held, source))
    after = held | frozenset(new)
    newly_exposed = sorted(gate.exposed(ix, after) - gate.exposed(ix, held))
    contradictions = tuple(
        Contradiction(
            lie=lie,
            exposer=min((e for e in ix.facts[lie].exposed_by if e in after), default=lie),
        )
        for lie in newly_exposed
    )
    opened = tuple(
        s
        for s in all_sources(ix)
        if not available_facts(ix, held, s) and available_facts(ix, after, s)
    )
    return state.with_facts(new), Outcome(SourceStatus.OK, new, contradictions, opened)
