"""The timeline stage: where every suspect is in every slot, and who could have done it."""

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import TimelineOut, TimelineRow, TruthOut
from gumshoe.cases.generate.streams import Stream


def run(ctx: GenContext, stream: Stream, truth: TruthOut) -> TimelineOut:
    roster, spec = truth.roster, ctx.spec
    records = {d.key: d for d in ctx.pack.record_defs}
    scene = roster.locations[0].pos
    others = [loc.pos for loc in roster.locations[1:]]
    kind_of = {loc.pos: loc.kind for loc in roster.locations}
    if spec.slots < 3:
        raise GenerationError("the timeline needs at least 3 slots")
    crime_slot = stream.choice(range(1, spec.slots - 1))
    wrong = [s.pos for s in roster.suspects[1:]]
    at_scene = set(stream.sample(wrong, spec.opportunity))

    rows = []
    for suspect in roster.suspects:
        attested = [p for p in others if kind_of[p] in records[suspect.record_kind].location_kinds]
        places = []
        for slot in range(spec.slots):
            if slot == crime_slot:
                if suspect.pos == "s0" or suspect.pos in at_scene:
                    places.append(scene)
                    continue
                if not attested:
                    raise GenerationError(f"{suspect.pos}: no non-scene place their record attests")
                places.append(stream.choice(attested))
            else:
                places.append(stream.choice([scene, *others]))
        rows.append(TimelineRow(suspect_pos=suspect.pos, places=tuple(places)))
    return TimelineOut(
        crime_slot=crime_slot,
        rows=tuple(rows),
        opportunity=tuple(s for s in wrong if s in at_scene),
    )
