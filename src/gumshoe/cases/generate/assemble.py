"""The assemble stage: a skeleton-only `Case` from the stage outputs, then its final ids.

`build_case` writes every skin field blank and every id as the neutral position the stages use
(`s0`, `m1`, `l2`, `e_s3_1`, `sec_s0`), so the culprit is still `s0`. A blank-skin case validates
exactly like a skinned one (overview 2.4), which is how the evidence stages get real validator
feedback before any wording exists. `assemble` then gives every entity its final id, a hash of
the case's code (seed, preset, pack), the kind of entity and its place in the sorted neutral
ids, so no id says who the culprit is, what a fact is or how early a stage drew it, and the
same seed gives other ids in another preset or pack. It draws nothing.
"""

from collections.abc import Mapping

from pydantic import ValidationError

from gumshoe.cases.core.ids import make_id
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import (
    PIPELINE,
    SKELETON_ALGO_VERSION,
    STAGE_VERSIONS,
    GenContext,
)
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
    return ",".join(f"{stage}={STAGE_VERSIONS[stage]}" for stage in PIPELINE)


# the id prefix of each kind of entity; every kind of fact shares one prefix, so a fact's final id
# says nothing about what the fact is
PREFIXES = {
    "suspect": "s",
    "method": "m",
    "motive": "v",
    "location": "l",
    "event": "e",
    "fact": "f",
}


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
        id=make_id("c", ctx.seed, ctx.preset, ctx.pack.id, ctx.pack.skeleton_hash(), ctx.spec_hash),
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


def id_map(case: Case) -> dict[str, str]:
    """Neutral id -> final id for every entity: `make_id(prefix, case.id, kind, index, salt)`,
    with `index` the entity's place among the sorted neutral ids of its kind and `case.id` the
    skeleton case's id (a hash of seed, preset, pack and spec). The hash is what hides the neutral
    order (the culprit is index 0 of the suspects), so the order of the final ids is as good as
    random; a collision with an earlier id raises the salt until the id is free, which is
    deterministic and in practice never happens."""
    groups = {
        "suspect": [s.id for s in case.suspects],
        "method": [m.id for m in case.methods],
        "motive": [v.id for v in case.motives],
        "location": [loc.id for loc in case.locations],
        "event": [e.id for e in case.timeline],
        "fact": [f.id for f in case.facts],
    }
    final: dict[str, str] = {}
    taken: set[str] = set()
    for kind, neutral in groups.items():
        for index, ident in enumerate(sorted(neutral)):
            salt = 0
            while (new := make_id(PREFIXES[kind], case.id, kind, index, salt)) in taken:
                salt += 1
            taken.add(new)
            final[ident] = new
    if len(final) != sum(len(g) for g in groups.values()):
        raise GenerationError("two entities share a neutral id")
    return final


def _ref(ref: dict[str, object], names: Mapping[str, str]) -> None:
    """Rename the ids inside a dumped `SourceRef` (a record's target is a kind, not an id)."""
    if ref["kind"] == SourceKind.RECORD.value:
        ref["subject"] = names[str(ref["subject"])]
    else:
        ref["target"] = names[str(ref["target"])]


def rename(case: Case, names: Mapping[str, str]) -> Case:
    """The same case with every id replaced, field by field. It goes through the dumped form and
    `Case.model_validate`, so every list comes out sorted by its new ids."""
    data = case.model_dump(mode="json")

    def many(ids: list[str]) -> list[str]:
        return [names[i] for i in ids]

    for s in data["suspects"]:
        for key in ("id", "motive", "secret_fact"):
            s[key] = names[s[key]]
        s["requires"], s["knows"] = many(s["requires"]), many(s["knows"])
    for loc in data["locations"]:
        loc["id"], loc["requires"] = names[loc["id"]], many(loc["requires"])
    for r in data["record_sources"]:
        r["subject"], r["requires"] = names[r["subject"]], many(r["requires"])
    for entity in (*data["methods"], *data["motives"]):
        entity["id"] = names[entity["id"]]
    for e in data["timeline"]:
        for key in ("id", "actor", "place"):
            e[key] = names[e[key]]
    for f in data["facts"]:
        f["id"] = names[f["id"]]
        f["requires"], f["exposed_by"] = many(f["requires"]), many(f["exposed_by"])
        f["timeline_ref"] = many(f["timeline_ref"])
        if f["speaker"] is not None:
            f["speaker"] = names[f["speaker"]]
        for effect in f["effects"]:
            effect["candidate"] = names[effect["candidate"]]
        if f["claim"] is not None:
            for key in ("actor", "place"):
                f["claim"][key] = names[f["claim"][key]]
        _ref(f["source"], names)
        if f["exposure_hook"] is not None:
            _ref(f["exposure_hook"], names)
    data["truth"] = {axis: names[ident] for axis, ident in data["truth"].items()}
    data["start"] = {part: many(ids) for part, ids in data["start"].items()}
    return Case.model_validate(data)


def assemble(
    ctx: GenContext,
    truth: TruthOut,
    timeline: TimelineOut,
    facts: FactsOut,
    placement: PlacementOut,
    gating: GatingOut,
) -> Case:
    """The skeleton-only case with its final ids: `build_case`, then `id_map` and `rename`. A
    stage output that does not make a case (a reference to nothing) is a `GenerationError`."""
    try:
        skeleton = build_case(ctx, truth, timeline, facts, placement, gating)
        return rename(skeleton, id_map(skeleton))
    except (KeyError, ValidationError) as error:
        raise GenerationError(f"a stage output does not make a case: {error!r}") from error
