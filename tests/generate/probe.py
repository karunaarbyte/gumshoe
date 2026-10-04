"""The structural probe: a partial Case built from the three stage outputs, run through the real
strict validator. Groups 6, 8 and 9 (solvability, difficulty, fairness) are skipped because the
case has no evidence yet; whatever else the validator reports must belong to later stages."""

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import TimelineOut, TruthOut
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Event,
    Fact,
    Location,
    Method,
    Motive,
    PackRef,
    RecordSource,
    SourceRef,
    Start,
    Suspect,
    Truth,
)
from gumshoe.cases.model.enums import FactKind, Origin, RecordSubjectType, SourceKind


def _record(kind: str, subject: str) -> SourceRef:
    return SourceRef(kind=SourceKind.RECORD, target=kind, subject=subject)


def probe_case(ctx: GenContext, truth: TruthOut, timeline: TimelineOut) -> Case:
    roster = truth.roster
    kind_of = {loc.pos: loc.kind for loc in roster.locations}
    records = {d.key: d for d in ctx.pack.record_defs}

    facts: list[Fact] = []
    sources: list[RecordSource] = []
    suspects: list[Suspect] = []
    for s in roster.suspects:
        fid = f"f_secret_{s.pos}"
        facts.append(
            Fact(id=fid, kind=FactKind.SECRET, source=_record(s.record_kind, s.pos), truthful=True)
        )
        sources.append(
            RecordSource(kind=s.record_kind, subject_type=RecordSubjectType.SUSPECT, subject=s.pos)
        )
        suspects.append(
            Suspect(
                id=s.pos,
                label=s.label,
                aliases=s.aliases,
                role=s.role,
                motive=s.motive_pos,
                secret_fact=fid,
            )
        )
    # one stub source for every chosen record kind that no suspect uses (contract (f))
    used = {s.record_kind for s in roster.suspects}
    for kind in roster.record_kinds:
        if kind in used:
            continue
        definition = records[kind]
        if definition.subject == "location":
            subject = next(
                loc.pos for loc in roster.locations if kind_of[loc.pos] in definition.location_kinds
            )
            subject_type = RecordSubjectType.LOCATION
        else:
            subject, subject_type = roster.suspects[0].pos, RecordSubjectType.SUSPECT
        sources.append(RecordSource(kind=kind, subject_type=subject_type, subject=subject))
        facts.append(Fact(id=f"f_stub_{kind}", kind=FactKind.CLUE, source=_record(kind, subject)))

    events = []
    for row in timeline.rows:
        for slot, place in enumerate(row.places):
            crime = slot == timeline.crime_slot and row.suspect_pos == truth.who_pos
            events.append(
                Event(
                    id=f"e_{row.suspect_pos}_{slot}",
                    slot=slot,
                    actor=row.suspect_pos,
                    place=place,
                    action="crime" if crime else "present",
                )
            )
    return Case(
        id="c_probe",
        origin=Origin.GENERATED,
        pack_ref=PackRef(id=ctx.pack.id, skeleton_hash=ctx.pack.skeleton_hash()),
        spec=ctx.spec,
        scene_type=roster.scene_type,
        truth=Truth(who=truth.who_pos, how=truth.how_pos, why=truth.why_pos),
        start=Start(
            locations=tuple(loc.pos for loc in roster.locations),
            suspects=tuple(s.pos for s in roster.suspects),
            facts=tuple(f.id for f in facts),
        ),
        suspects=tuple(suspects),
        locations=tuple(Location(id=loc.pos, kind=loc.kind) for loc in roster.locations),
        record_sources=tuple(sources),
        methods=tuple(
            Method(id=m.pos, label=m.label, aliases=m.aliases, type=m.key) for m in roster.methods
        ),
        motives=tuple(
            Motive(id=m.pos, label=m.label, aliases=m.aliases, type=m.key) for m in roster.motives
        ),
        timeline=tuple(events),
        facts=tuple(facts),
    )
