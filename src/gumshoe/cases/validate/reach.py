"""Reachability fixpoint: what can a player ever find, starting from `start`?"""

from dataclasses import dataclass

from gumshoe.cases.model.entities import SourceRef
from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.model.index import CaseIndex


@dataclass(frozen=True)
class Reach:
    facts: frozenset[str]
    locations: frozenset[str]
    suspects: frozenset[str]
    record_sources: frozenset[tuple[str, str]]


def _accessible(
    index: CaseIndex, discovered: set[str]
) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    case = index.case
    locations = {
        loc.id
        for loc in case.locations
        if loc.id in case.start.locations
        or (loc.requires and all(r in discovered for r in loc.requires))
    }
    suspects = {
        s.id
        for s in case.suspects
        if s.id in case.start.suspects or (s.requires and all(r in discovered for r in s.requires))
    }
    records = {
        key for key, rs in index.record_sources.items() if all(r in discovered for r in rs.requires)
    }
    return locations, suspects, records


def _open(
    source: SourceRef, locations: set[str], suspects: set[str], records: set[tuple[str, str]]
) -> bool:
    if source.kind is SourceKind.SEARCH:
        return source.target in locations
    if source.kind is SourceKind.INTERROGATE:
        return source.target in suspects
    return (source.target, source.subject or "") in records


def compute_reach(index: CaseIndex, removed: frozenset[str] = frozenset()) -> Reach:
    case = index.case
    discovered = {f for f in case.start.facts if f in index.facts and f not in removed}
    changed = True
    while changed:
        changed = False
        locations, suspects, records = _accessible(index, discovered)
        for fact in case.facts:
            if fact.id in discovered or fact.id in removed:
                continue
            if _open(fact.source, locations, suspects, records) and all(
                r in discovered for r in fact.requires
            ):
                discovered.add(fact.id)
                changed = True
    locations, suspects, records = _accessible(index, discovered)
    return Reach(
        frozenset(discovered), frozenset(locations), frozenset(suspects), frozenset(records)
    )
