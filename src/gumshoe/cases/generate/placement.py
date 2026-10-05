"""The placement stage: where every search fact is found, and what each location record is about.

Placement shares one resource, the number of facts at each location, so the order in which things
are placed matters. It is therefore always a shuffled order from a stream that knows nothing about
who the culprit is, never the canonical order (culprit first); ties between equally loaded
locations are broken by a draw keyed by the entity being placed.
"""

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    FactDesc,
    FactsOut,
    PlacedFact,
    PlacedRecord,
    PlacementOut,
    TruthOut,
)
from gumshoe.cases.generate.streams import Stream


class _Loads:
    """How many search facts each location holds, and where each placed fact went."""

    def __init__(self, locations: list[str], cap: int) -> None:
        self.load = dict.fromkeys(locations, 0)
        self.where: dict[str, str] = {}
        self.cap = cap

    def put(self, fact: str, location: str) -> None:
        self.load[location] += 1
        self.where[fact] = location

    def least_loaded(self, candidates: list[str]) -> list[str]:
        """The candidates with room, keeping only those holding the fewest facts."""
        roomy = [loc for loc in candidates if self.load[loc] < self.cap]
        if not roomy:
            return []
        fewest = min(self.load[loc] for loc in roomy)
        return [loc for loc in roomy if self.load[loc] == fewest]


def _place(loads: _Loads, fact: FactDesc, candidates: list[str], stream: Stream) -> None:
    best = loads.least_loaded(candidates)
    if not best:
        raise GenerationError(f"no location with room can hold {fact.id}")
    loads.put(fact.id, stream.child(f"tie/{fact.id}").choice(best))


def _search_facts(facts: FactsOut, prefix: str) -> list[FactDesc]:
    return [f for f in facts.facts if f.home.kind == "search" and f.id.startswith(prefix)]


def _decisive_and_clues(
    loads: _Loads, facts: FactsOut, kind_of: dict[str, str], stream: Stream
) -> None:
    """Each method's decisive trace at a location its trace allows, then its clue elsewhere."""
    locations = list(kind_of)
    decisive = _search_facts(facts, "h_")
    for fact in stream.child("order/decisive").shuffle(decisive):
        allowed = [loc for loc in locations if kind_of[loc] in fact.place_kinds]
        _place(loads, fact, allowed, stream)
    clues = _search_facts(facts, "p_")
    for fact in stream.child("order/clues").shuffle(clues):
        apart = loads.where[fact.apart_from] if fact.apart_from else None
        _place(loads, fact, [loc for loc in locations if loc != apart], stream)


def _require_every_location_used(loads: _Loads) -> None:
    """Every location must hold a search fact. Clues go to the least loaded location, so an empty
    location is always filled first; one still empty here means there are fewer facts than
    locations (the feasibility rule `L <= 2M` keeps that from happening)."""
    empty = [loc for loc, count in loads.load.items() if count == 0]
    if empty:
        raise GenerationError(f"no search fact was placed at {empty[0]}")


def _keys(loads: _Loads, facts: FactsOut, stream: Stream) -> None:
    """The depth-2 keys, one per suspect, in a shuffled order: least loaded location first."""
    keys = _search_facts(facts, "c_")
    for fact in stream.child("order/keys").shuffle(keys):
        _place(loads, fact, list(loads.load), stream)


def _record_sources(
    ctx: GenContext, facts: FactsOut, kind_of: dict[str, str], stream: Stream
) -> tuple[PlacedRecord, ...]:
    records = {d.key: d for d in ctx.pack.record_defs}
    placed: list[PlacedRecord] = []
    for source in facts.record_sources:
        if source.subject is not None:
            placed.append(
                PlacedRecord(kind=source.kind, subject_type="suspect", subject=source.subject)
            )
            continue
        allowed = [loc for loc in kind_of if kind_of[loc] in records[source.kind].location_kinds]
        if not allowed:
            raise GenerationError(f"no chosen location can be the subject of {source.kind!r}")
        subject = stream.child(f"record/{source.kind}").choice(allowed)
        placed.append(PlacedRecord(kind=source.kind, subject_type="location", subject=subject))
    return tuple(placed)


def run(ctx: GenContext, stream: Stream, truth: TruthOut, facts: FactsOut) -> PlacementOut:
    kind_of = {loc.pos: loc.kind for loc in truth.roster.locations}
    loads = _Loads(list(kind_of), ctx.spec.source_cap)
    _decisive_and_clues(loads, facts, kind_of, stream)
    _require_every_location_used(loads)
    _keys(loads, facts, stream)
    return PlacementOut(
        search=tuple(PlacedFact(fact=f, location=loc) for f, loc in sorted(loads.where.items())),
        record_sources=_record_sources(ctx, facts, kind_of, stream),
    )
