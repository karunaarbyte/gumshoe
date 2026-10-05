"""The gating stage: which facts unlock which sources, and what a player can use at the start.

Gating only wires: every fact already exists (the facts stage made the hints and the keys) and
placement put them somewhere. One depth holds for every suspect, and each suspect's chain is
their own: at depth 1 a suspect's record needs the hint they give when questioned, at depth 2
questioning them also needs their key. The chains share no fact, so the proves route and the
elimination route of every axis share no gate, and losing any one fact leaves every axis
decidable. Nothing here is drawn, so the stage never reads its stream.
"""

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    FactsOut,
    GatingOut,
    PlacementOut,
    RecordGate,
    SuspectGate,
    TruthOut,
)
from gumshoe.cases.generate.streams import Stream


def run(
    ctx: GenContext, stream: Stream, truth: TruthOut, facts: FactsOut, placement: PlacementOut
) -> GatingOut:
    roster, depth = truth.roster, facts.depth
    ids = {f.id for f in facts.facts}
    suspect_gates: list[SuspectGate] = []
    record_gates: list[RecordGate] = []
    for s in roster.suspects:
        hint, key = f"y_{s.pos}", f"c_{s.pos}"
        if depth >= 1:
            if hint not in ids:
                raise GenerationError(f"depth {depth} needs the hint {hint}, which has no fact")
            record_gates.append(RecordGate(kind=s.record_kind, subject=s.pos, fact=hint))
        if depth == 2:
            if key not in ids:
                raise GenerationError(f"depth 2 needs the key {key}, which has no fact")
            suspect_gates.append(SuspectGate(suspect=s.pos, fact=key))
    locked = {g.suspect for g in suspect_gates}
    return GatingOut(
        depth=depth,
        suspect_requires=tuple(sorted(suspect_gates, key=lambda g: g.suspect)),
        record_requires=tuple(sorted(record_gates, key=lambda g: (g.kind, g.subject))),
        start_locations=tuple(loc.pos for loc in roster.locations),
        start_suspects=tuple(s.pos for s in roster.suspects if s.pos not in locked),
        start_facts=(),
    )
