"""`build_case`: a skeleton-only `Case` from the stage outputs.

Every skin field stays blank and every id is the neutral position the stages use (`s0`, `m1`,
`l2`, `e_s3_1`, `sec_s0`), so the culprit is still `s0`: the permutation and the final ids are
2d-3's `assemble`. A blank-skin case validates exactly like a skinned one (overview 2.4), which
is how the evidence stages get real validator feedback before any wording exists.
"""

from gumshoe.cases.core.ids import make_id
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import SKELETON_ALGO_VERSION, STAGE_VERSIONS, GenContext
from gumshoe.cases.generate.outputs import (
    FactDesc,
    FactsOut,
    GatingOut,
    HomeDesc,
    PlacementOut,
    TimelineOut,
    TruthOut,
)
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Claim,
    Effect,
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
from gumshoe.cases.model.enums import (
    Axis,
    ClaimKind,
    EffectKind,
    FactKind,
    Origin,
    RecordSubjectType,
    SourceKind,
)

CRIME, PRESENT = "crime", "present"


def generator_version() -> str:
    """Every stage version in pipeline order, as `Case.generator_version` records it."""
    return ",".join(f"{stage}={version}" for stage, version in STAGE_VERSIONS.items())


def _source(
    home: HomeDesc, search: dict[str, str], located: dict[str, str], fact: str
) -> SourceRef:
    """The `SourceRef` of a home: a record about its subject (a location record's subject comes
    from placement), a suspect to question, or the location placement chose for a search fact."""
    if home.kind == "record":
        subject = home.subject if home.subject is not None else located.get(home.target or "")
        if home.target is None or subject is None:
            raise GenerationError(f"{fact} sits on a record source with no subject")
        return SourceRef(kind=SourceKind.RECORD, target=home.target, subject=subject)
    if home.kind == "interrogate":
        if home.target is None:
            raise GenerationError(f"{fact} is asked of nobody")
        return SourceRef(kind=SourceKind.INTERROGATE, target=home.target)
    if fact not in search:
        raise GenerationError(f"{fact} is a search fact that placement did not place")
    return SourceRef(kind=SourceKind.SEARCH, target=search[fact])


def _fact(desc: FactDesc, search: dict[str, str], located: dict[str, str]) -> Fact:
    claim = desc.claim
    return Fact(
        id=desc.id,
        kind=FactKind(desc.kind),
        source=_source(desc.home, search, located, desc.id),
        requires=desc.requires,
        effects=tuple(
            Effect(axis=Axis(e.axis), candidate=e.candidate, kind=EffectKind(e.kind))
            for e in desc.effects
        ),
        trace_kind=desc.trace_kind,
        claim=None
        if claim is None
        else Claim(kind=ClaimKind.PRESENCE, actor=claim.actor, slot=claim.slot, place=claim.place),
        truthful=desc.truthful,
        speaker=desc.speaker,
        exposed_by=desc.exposed_by,
        exposure_hook=None
        if desc.exposure_hook is None
        else _source(desc.exposure_hook, search, located, desc.id),
        timeline_ref=desc.timeline_ref,
    )


def _events(truth: TruthOut, timeline: TimelineOut) -> tuple[Event, ...]:
    """One event per suspect and slot; the culprit's crime-slot cell is the crime."""
    return tuple(
        Event(
            id=f"e_{row.suspect_pos}_{slot}",
            slot=slot,
            actor=row.suspect_pos,
            place=place,
            action=CRIME
            if row.suspect_pos == truth.who_pos and slot == timeline.crime_slot
            else PRESENT,
        )
        for row in timeline.rows
        for slot, place in enumerate(row.places)
    )


def build_case(
    ctx: GenContext,
    truth: TruthOut,
    timeline: TimelineOut,
    facts: FactsOut,
    placement: PlacementOut,
    gating: GatingOut,
) -> Case:
    roster = truth.roster
    search = {p.fact: p.location for p in placement.search}
    located = {r.kind: r.subject for r in placement.record_sources if r.subject_type == "location"}
    built = tuple(_fact(f, search, located) for f in facts.facts)
    suspect_gate = {g.suspect: g.fact for g in gating.suspect_requires}
    record_gate = {(g.kind, g.subject): g.fact for g in gating.record_requires}
    suspects = tuple(
        Suspect(
            id=s.pos,
            label=s.label,
            aliases=s.aliases,
            role=s.role,
            motive=s.motive_pos,
            secret_fact=f"sec_{s.pos}",
            requires=(suspect_gate[s.pos],) if s.pos in suspect_gate else (),
            knows=tuple(
                f.id
                for f in built
                if f.speaker == s.pos
                or (f.source.kind is SourceKind.INTERROGATE and f.source.target == s.pos)
            ),
        )
        for s in roster.suspects
    )
    sources = tuple(
        RecordSource(
            kind=r.kind,
            subject_type=RecordSubjectType(r.subject_type),
            subject=r.subject,
            requires=(record_gate[r.kind, r.subject],)
            if (r.kind, r.subject) in record_gate
            else (),
        )
        for r in placement.record_sources
    )
    return Case(
        id=make_id("c", ctx.seed, ctx.preset, ctx.spec_hash),
        seed=ctx.seed,
        origin=Origin.GENERATED,
        pack_ref=PackRef(id=ctx.pack.id, skeleton_hash=ctx.pack.skeleton_hash()),
        generator_version=generator_version(),
        skeleton_algo_version=SKELETON_ALGO_VERSION,
        spec=ctx.spec,
        scene_type=roster.scene_type,
        truth=Truth(who=truth.who_pos, how=truth.how_pos, why=truth.why_pos),
        start=Start(
            locations=gating.start_locations,
            suspects=gating.start_suspects,
            facts=gating.start_facts,
        ),
        suspects=suspects,
        locations=tuple(
            Location(id=loc.pos, kind=loc.kind, decorative=loc.decorative)
            for loc in roster.locations
        ),
        record_sources=sources,
        methods=tuple(
            Method(id=m.pos, label=m.label, aliases=m.aliases, type=m.key) for m in roster.methods
        ),
        motives=tuple(
            Motive(id=v.pos, label=v.label, aliases=v.aliases, type=v.key) for v in roster.motives
        ),
        timeline=_events(truth, timeline),
        facts=built,
    )
