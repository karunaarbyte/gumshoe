"""A naive reference for reachability and ancestry: slow, obvious, written from the plain rules."""

import random

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import SourceKind


def _source_open(case: Case, fact, discovered: set[str]) -> bool:
    src = fact.source
    if src.kind is SourceKind.SEARCH:
        loc = next((x for x in case.locations if x.id == src.target), None)
        return loc is not None and (
            loc.id in case.start.locations
            or (bool(loc.requires) and all(r in discovered for r in loc.requires))
        )
    if src.kind is SourceKind.INTERROGATE:
        sus = next((x for x in case.suspects if x.id == src.target), None)
        return sus is not None and (
            sus.id in case.start.suspects
            or (bool(sus.requires) and all(r in discovered for r in sus.requires))
        )
    rs = next(
        (x for x in case.record_sources if (x.kind, x.subject) == (src.target, src.subject)), None
    )
    return rs is not None and all(r in discovered for r in rs.requires)


def naive_reach(case: Case) -> frozenset[str]:
    known = {f.id for f in case.facts}
    discovered = set(case.start.facts) & known
    while True:
        new = {
            f.id
            for f in case.facts
            if f.id not in discovered
            and all(r in discovered for r in f.requires)
            and _source_open(case, f, discovered)
        }
        if not new:
            return frozenset(discovered)
        discovered |= new


def _direct(case: Case, fact) -> set[str]:
    src, deps = fact.source, set(fact.requires)
    if src.kind is SourceKind.SEARCH:
        loc = next((x for x in case.locations if x.id == src.target), None)
        deps |= set(loc.requires) if loc else set()
    elif src.kind is SourceKind.INTERROGATE:
        sus = next((x for x in case.suspects if x.id == src.target), None)
        deps |= set(sus.requires) if sus else set()
    else:
        rs = next(
            (x for x in case.record_sources if (x.kind, x.subject) == (src.target, src.subject)),
            None,
        )
        deps |= set(rs.requires) if rs else set()
    return deps & {f.id for f in case.facts}


def naive_ancestors(case: Case) -> dict[str, frozenset[str]] | None:
    """Transitive closure by relaxation; None if any fact requires itself (transitively)."""
    direct = {f.id: _direct(case, f) for f in case.facts}
    closure = {i: set(d) for i, d in direct.items()}
    changed = True
    while changed:
        changed = False
        for i in closure:
            bigger = set(closure[i])
            for parent in list(closure[i]):
                bigger |= closure[parent]
            if bigger != closure[i]:
                closure[i], changed = bigger, True
    if any(i in closure[i] for i in closure):
        return None
    return {i: frozenset(c) for i, c in closure.items()}


def random_gates(case: Case, rng: random.Random) -> Case:
    """Random `requires` on facts, locations, suspects and record sources, and a random start."""
    ids = [f.id for f in case.facts]
    facts = []
    for f in case.facts:
        if rng.random() < 0.3:
            f = f.model_copy(update={"requires": tuple(rng.sample(ids, rng.randint(0, 2)))})
        facts.append(f)
    locations = tuple(
        x.model_copy(update={"requires": tuple(rng.sample(ids, rng.randint(0, 2)))})
        if rng.random() < 0.3
        else x
        for x in case.locations
    )
    suspects = tuple(
        x.model_copy(update={"requires": tuple(rng.sample(ids, rng.randint(0, 1)))})
        if rng.random() < 0.2
        else x
        for x in case.suspects
    )
    records = tuple(
        x.model_copy(update={"requires": tuple(rng.sample(ids, rng.randint(0, 2)))})
        if rng.random() < 0.3
        else x
        for x in case.record_sources
    )
    start = case.start.model_copy(
        update={
            "locations": tuple(x.id for x in locations if rng.random() < 0.7),
            "suspects": tuple(x.id for x in suspects if rng.random() < 0.8),
            "facts": tuple(rng.sample(ids, rng.randint(0, 2))),
        }
    )
    return case.model_copy(
        update={
            "facts": tuple(facts),
            "locations": locations,
            "suspects": suspects,
            "record_sources": records,
            "start": start,
        }
    )
