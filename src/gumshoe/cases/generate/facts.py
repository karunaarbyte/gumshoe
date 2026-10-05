"""The facts stage: every fact of the case, before any is placed or gated.

Every suspect gets exactly five facts, every method two, so no one is singled out by how much
there is to find. The shape is the same in every case (see the 2d-2 spec, section 3); what varies
is who is at the scene, where, and the gating depth.
"""

from gumshoe.cases.core.ids import is_valid_id
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    ClaimDesc,
    EffectDesc,
    FactDesc,
    FactsOut,
    HomeDesc,
    RecordSourceDesc,
    RosterOut,
    TimelineOut,
    TruthOut,
)
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.model.entities import Spec
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind
from gumshoe.cases.model.pack import MethodDef, Pack, TraceDef

DEPTHS = (0, 1, 2)  # 0: no gate; 1: records need a hint; 2: suspects also need a key
WHO, HOW, WHY = Axis.WHO.value, Axis.HOW.value, Axis.WHY.value
RULES_OUT, SUPPORTS, PROVES = (
    EffectKind.RULES_OUT.value,
    EffectKind.SUPPORTS.value,
    EffectKind.PROVES.value,
)


def feasible_depths(spec: Spec, location_records: int) -> list[int]:
    """The gating depths that fit the preset's windows and the source capacity, in order.

    The cheapest solution of a depth-d case is the incriminating item, the secret and the how
    proof (with its clue), plus the gate chain: size 4 + d, depth max(1, d), and 3 distinct
    sources (the culprit's record and the two search locations), 4 once a hint must be found.
    Depth 2 may need a fifth action (the culprit's key at a third location). Every depth also
    needs the decisive facts (three) to stay within their share of all facts, and no more than
    two locations per method, or placement leaves a location empty."""
    # interrogation capacity (2S facts over S sources) is implied by cap >= 3, so no clause
    limits, cap = spec.limits, spec.source_cap
    suspects, methods, locations = spec.suspects, spec.methods, spec.locations
    found = []
    for d in DEPTHS:
        fewest, most = (3, 3) if d == 0 else (4, 5 if d == 2 else 4)  # actions of the cheapest
        if not (
            limits.solution_min <= 4 + d <= limits.solution_max
            and limits.depth_min <= max(1, d) <= limits.depth_max
            and limits.actions_min <= fewest
            and most <= limits.actions_max
        ):
            continue
        total = 5 * suspects + 2 * methods + location_records + (suspects if d == 2 else 0)
        if limits.decisive_pct_max * total < 300 or locations > 2 * methods:
            continue
        search = 2 * methods + (suspects if d == 2 else 0)
        records = 3 * suspects + location_records
        record_sources = suspects + location_records
        if (
            search * 5 <= 4 * cap * locations  # the validator's 0.8 x cap x sources rule
            and records * 5 <= 4 * cap * record_sources
            and cap >= 3
        ):
            found.append(d)
    return found


def _effect(axis: str, candidate: str, kind: str) -> EffectDesc:
    return EffectDesc(axis=axis, candidate=candidate, kind=kind)


def _event(pos: str, slot: int) -> str:
    return f"e_{pos}_{slot}"


def _suspect_facts(
    pack: Pack,
    roster: RosterOut,
    timeline: TimelineOut,
    slots: int,
    stream: Stream,
) -> list[FactDesc]:
    """The five facts of every suspect: secret, presence at the crime slot, a physical item or a
    second presence, a motive hint, and one lie that the suspect's own record exposes."""
    records = {d.key: d for d in pack.record_defs}
    kind_of = {loc.pos: loc.kind for loc in roster.locations}
    rows = {row.suspect_pos: row.places for row in timeline.rows}
    crime = timeline.crime_slot
    opportunity = set(timeline.opportunity)
    out: list[FactDesc] = []
    for s in roster.suspects:
        k, record = s.pos, HomeDesc(kind="record", target=s.record_kind, subject=s.pos)
        at_scene = k == "s0" or k in opportunity
        true_place = rows[k][crime]
        out.append(
            FactDesc(
                id=f"sec_{k}",
                kind=FactKind.SECRET.value,
                effects=(_effect(WHY, s.motive_pos, PROVES if k == "s0" else RULES_OUT),),
                home=record,
            )
        )
        out.append(
            FactDesc(
                id=f"e_{k}",
                kind=(FactKind.PRESENCE if at_scene else FactKind.ALIBI).value,
                effects=(_effect(WHO, k, SUPPORTS if at_scene else RULES_OUT),),
                claim=ClaimDesc(actor=k, slot=crime, place=true_place),
                timeline_ref=(_event(k, crime),),
                home=record,
            )
        )
        if at_scene:
            out.append(
                FactDesc(
                    id=f"x_{k}",
                    kind=FactKind.PHYSICAL.value,
                    effects=(_effect(WHO, k, PROVES if k == "s0" else RULES_OUT),),
                    home=record,
                )
            )
        else:
            other_slots = [t for t in range(slots) if t != crime]
            attested = [
                t
                for t in other_slots
                if kind_of[rows[k][t]] in records[s.record_kind].location_kinds
            ]
            slot = stream.child(f"w/{k}").choice(attested or other_slots)
            out.append(
                FactDesc(
                    id=f"w_{k}",
                    kind=FactKind.PRESENCE.value,
                    effects=(_effect(WHO, k, SUPPORTS),),
                    claim=ClaimDesc(actor=k, slot=slot, place=rows[k][slot]),
                    timeline_ref=(_event(k, slot),),
                    home=record,
                )
            )
        ask = HomeDesc(kind="interrogate", target=k)
        out.append(
            FactDesc(
                id=f"y_{k}",
                kind=FactKind.MOTIVE_CLUE.value,
                effects=(_effect(WHY, s.motive_pos, SUPPORTS),),
                speaker=k,
                home=ask,
            )
        )
        non_scene = [loc.pos for loc in roster.locations[1:]]
        if not non_scene:
            raise GenerationError(f"{k} has no non-scene place to lie about")
        # every suspect's lie avoids one decoy place, so the lie's place does not tell who was
        # at the scene: an away suspect's decoy is their crime place, which the timeline drew
        # among the places their record attests, and an at-scene suspect gets a place their
        # record attests too
        if at_scene:
            attested_places = [
                p for p in non_scene if kind_of[p] in records[s.record_kind].location_kinds
            ]
            if not attested_places:
                raise GenerationError(f"{k}'s record kind attests no non-scene place")
            decoy = stream.child(f"decoy/{k}").choice(attested_places)
        else:
            decoy = true_place
        lie_places = [p for p in non_scene if p != decoy]
        if not lie_places:
            raise GenerationError(f"{k} has no non-scene place to lie about")
        out.append(
            FactDesc(
                id=f"l_{k}",
                kind=FactKind.LIE.value,
                effects=(_effect(WHO, k, RULES_OUT),),
                claim=ClaimDesc(
                    actor=k, slot=crime, place=stream.child(f"lie/{k}").choice(lie_places)
                ),
                truthful=False,
                speaker=k,
                exposed_by=(f"e_{k}",),
                exposure_hook=record,
                home=ask,
            )
        )
    return out


def _fitting_traces(method: MethodDef, pack: Pack, roster: RosterOut) -> list[TraceDef]:
    scene = next(sc for sc in pack.scene_types if sc.key == roster.scene_type)
    chosen = {loc.kind for loc in roster.locations}
    return [
        t
        for t in method.traces
        if t.kind in scene.allowed_trace_kinds and chosen & set(t.location_kinds)
    ]


def _method_facts(pack: Pack, roster: RosterOut, stream: Stream) -> list[FactDesc]:
    """Two search facts per method: the decisive trace (a proof for the true method, an absence
    for the others), which is only found after its supporting clue, and the clue itself."""
    methods = {m.key: m for m in pack.method_defs}
    out: list[FactDesc] = []
    for m in roster.methods:
        fitting = _fitting_traces(methods[m.key], pack, roster)
        if not fitting:
            raise GenerationError(f"method {m.key!r} has no trace that fits the scene")
        trace = stream.child(f"trace/{m.pos}").choice(fitting)
        true_method = m.pos == "m0"
        out.append(
            FactDesc(
                id=f"h_{m.pos}",
                kind=(FactKind.TRACE if true_method else FactKind.ABSENT_TRACE).value,
                effects=(_effect(HOW, m.pos, PROVES if true_method else RULES_OUT),),
                trace_kind=trace.kind,
                requires=(f"p_{m.pos}",),
                home=HomeDesc(kind="search"),
                place_kinds=tuple(trace.location_kinds),
            )
        )
        out.append(
            FactDesc(
                id=f"p_{m.pos}",
                kind=FactKind.CLUE.value,
                effects=(_effect(HOW, m.pos, SUPPORTS),),
                home=HomeDesc(kind="search"),
                apart_from=f"h_{m.pos}",
            )
        )
    return out


def run(
    ctx: GenContext,
    stream: Stream,
    truth: TruthOut,
    timeline: TimelineOut,
    depth: int | None = None,
) -> FactsOut:
    """The facts of the case. `depth` forces a gating depth (tests); `None` draws one from the
    depths that fit the preset and the pack."""
    roster, spec, pack = truth.roster, ctx.spec, ctx.pack
    records = {d.key: d for d in pack.record_defs}
    location_kinds = [k for k in roster.record_kinds if records[k].subject == "location"]
    feasible = feasible_depths(spec, len(location_kinds))
    if not feasible:
        raise GenerationError(
            f"no gating depth fits the {ctx.preset!r} preset on this pack "
            "(its solution, depth and action windows, or the source capacity, rule out 0, 1 and 2)"
        )
    if depth is None:
        depth = stream.child("depth").choice(feasible)
    elif depth not in feasible:
        raise GenerationError(f"depth {depth} is not feasible here (feasible: {feasible})")

    facts = _suspect_facts(pack, roster, timeline, spec.slots, stream)
    facts += _method_facts(pack, roster, stream)
    for kind in location_kinds:  # a neutral entry, so the kind has a source with something in it
        facts.append(
            FactDesc(
                id=f"n_{kind}",
                kind=FactKind.CLUE.value,
                home=HomeDesc(kind="record", target=kind),
            )
        )
    if depth == 2:  # a neutral key per suspect: found by searching, it unlocks questioning them
        facts += [
            FactDesc(id=f"c_{s.pos}", kind=FactKind.CLUE.value, home=HomeDesc(kind="search"))
            for s in roster.suspects
        ]
    bad = [f.id for f in facts if not is_valid_id(f.id)]
    if bad:
        raise GenerationError(f"fact ids are not valid ids: {bad}")
    sources = [
        RecordSourceDesc(kind=s.record_kind, subject_type="suspect", subject=s.pos)
        for s in roster.suspects
    ]
    sources += [
        RecordSourceDesc(kind=kind, subject_type="location", subject=None)
        for kind in location_kinds
    ]
    return FactsOut(depth=depth, facts=tuple(facts), record_sources=tuple(sources))
