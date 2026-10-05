"""The fold over the structural stages. 2d-3's pipeline replaces it with the retry controller;
until then every stage runs once, with stream counter 0."""

from collections.abc import Mapping

from gumshoe.cases.generate import facts, placement, roster, timeline, truth
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import STAGES, GenContext
from gumshoe.cases.generate.outputs import (
    FactsOut,
    Output,
    PlacementOut,
    RosterOut,
    TimelineOut,
    TruthOut,
)

OUTPUT_TYPES: dict[str, type[Output]] = {
    "roster": RosterOut,
    "truth": TruthOut,
    "timeline": TimelineOut,
    "facts": FactsOut,
    "placement": PlacementOut,
}


def run_structure(
    ctx: GenContext,
    upto: str | None = None,
    override: Mapping[str, Output] | None = None,
) -> dict[str, Output]:
    """Run the stages in order up to and including `upto` (the last stage when None). An override
    replaces that stage's output instead of running it, and the later stages run on top of it.
    An override for a stage after `upto` is type-checked (roster, truth and timeline overrides
    are also size-checked) but otherwise ignored; the checks that need a computed truth (the
    timeline's rows, the facts and the placement) run when the loop reaches that stage. A truth
    override replaces the roster entry by its own roster (unless the roster is itself
    overridden), so the returned dict stays consistent: with a truth override and no roster
    override the returned `roster` entry is the truth's (reordered) roster, not the pre-truth
    roster. Overrides are checked against `ctx.spec` and each other."""
    override = override or {}
    upto = STAGES[-1] if upto is None else upto
    if upto not in STAGES:
        raise ValueError(f"unknown stage {upto!r} (stages: {', '.join(STAGES)})")
    unknown = sorted(set(override) - set(STAGES))
    if unknown:
        raise ValueError(f"unknown override stage(s): {', '.join(unknown)}")
    for stage, value in override.items():
        if not isinstance(value, OUTPUT_TYPES[stage]):
            raise TypeError(
                f"the {stage} override must be a {OUTPUT_TYPES[stage].__name__}, "
                f"not {type(value).__name__}"
            )
    _check_overrides(ctx, override)
    out: dict[str, Output] = {}
    for stage in STAGES:
        if stage == "timeline" and stage in override:
            _check_timeline_rows(_need(out, "truth", TruthOut), override[stage])
        if stage == "facts" and stage in override:
            _check_facts(ctx, _need(out, "truth", TruthOut), override[stage])
        if stage == "placement" and stage in override:
            _check_placement(
                ctx,
                _need(out, "truth", TruthOut),
                _need(out, "facts", FactsOut),
                override[stage],
            )
        if stage in override:
            out[stage] = override[stage]
        elif stage == "roster":
            out[stage] = roster.run(ctx, ctx.stream(stage))
        elif stage == "truth":
            out[stage] = truth.run(ctx, ctx.stream(stage), _need(out, "roster", RosterOut))
        elif stage == "timeline":
            out[stage] = timeline.run(ctx, ctx.stream(stage), _need(out, "truth", TruthOut))
        elif stage == "facts":
            out[stage] = facts.run(
                ctx,
                ctx.stream(stage),
                _need(out, "truth", TruthOut),
                _need(out, "timeline", TimelineOut),
            )
        else:
            out[stage] = placement.run(
                ctx,
                ctx.stream(stage),
                _need(out, "truth", TruthOut),
                _need(out, "facts", FactsOut),
            )
        if stage == "truth" and stage in override and "roster" not in override:
            out["roster"] = _need(out, "truth", TruthOut).roster
        if stage == upto:
            break
    return out


def _check_roster(ctx: GenContext, stage: str, roster: RosterOut) -> None:
    spec = ctx.spec
    sizes = {
        "suspects": (len(roster.suspects), spec.suspects),
        "methods": (len(roster.methods), spec.methods),
        "motives": (len(roster.motives), spec.motives),
        "locations": (len(roster.locations), spec.locations),
        "record kinds": (len(roster.record_kinds), spec.record_kinds),
    }
    for what, (found, wanted) in sizes.items():
        if found != wanted:
            raise ValueError(
                f"the {stage} override has {found} {what}, the {ctx.preset!r} preset needs {wanted}"
            )


def _check_roster_kinds(ctx: GenContext, stage: str, roster: RosterOut) -> None:
    """The record kinds are the pack's, and each suspect holds one their role allows."""
    subject = {d.key: d.subject for d in ctx.pack.record_defs}
    roles = {r.key: r for r in ctx.pack.roles}
    unknown = sorted(set(roster.record_kinds) - set(subject))
    if unknown:
        raise ValueError(f"the {stage} override has undefined record kinds: {unknown}")
    for s in roster.suspects:
        role = roles.get(s.role)
        if role is None or s.record_kind not in role.record_kinds:
            raise ValueError(
                f"the {stage} override gives {s.pos} the record kind {s.record_kind!r}, "
                f"which their role {s.role!r} does not allow"
            )
        if subject.get(s.record_kind) != "suspect" or s.record_kind not in roster.record_kinds:
            raise ValueError(
                f"the {stage} override gives {s.pos} the record kind {s.record_kind!r}, "
                "which is not a suspect record kind of the roster"
            )
    held = {s.record_kind for s in roster.suspects}
    orphans = sorted(k for k in roster.record_kinds if subject[k] == "suspect" and k not in held)
    if orphans:
        raise ValueError(f"the {stage} override has suspect record kinds nobody holds: {orphans}")


def _check_timeline(ctx: GenContext, timeline: TimelineOut) -> None:
    spec = ctx.spec
    if timeline.crime_slot not in range(1, spec.slots - 1):
        raise ValueError(
            f"the timeline override has crime slot {timeline.crime_slot}, "
            f"the {ctx.preset!r} preset has slots 0 to {spec.slots - 1} and needs one inside them"
        )
    if len(timeline.opportunity) != spec.opportunity:
        raise ValueError(
            f"the timeline override has {len(timeline.opportunity)} opportunity suspects, "
            f"the {ctx.preset!r} preset needs {spec.opportunity}"
        )
    for row in timeline.rows:
        if len(row.places) != spec.slots:
            raise ValueError(
                f"the timeline override has {len(row.places)} slots for {row.suspect_pos}, "
                f"the {ctx.preset!r} preset needs {spec.slots}"
            )


def _check_timeline_rows(truth: TruthOut, timeline: Output) -> None:
    """A timeline override must be about the truth's suspects and places."""
    if not isinstance(timeline, TimelineOut):
        return
    roster = truth.roster
    if len(timeline.rows) != len(roster.suspects):
        raise ValueError(
            f"the timeline override has {len(timeline.rows)} rows for "
            f"{len(roster.suspects)} suspects"
        )
    suspects = {s.pos for s in roster.suspects}
    if {row.suspect_pos for row in timeline.rows} != suspects:
        raise ValueError("the timeline override must have a row for each of the truth's suspects")
    places = {loc.pos for loc in roster.locations}
    stray = {p for row in timeline.rows for p in row.places} - places
    if stray:
        raise ValueError(f"the timeline override has places outside the roster: {sorted(stray)}")
    if "s0" in timeline.opportunity or not set(timeline.opportunity) <= suspects:
        raise ValueError("the timeline override's opportunity must be wrong suspects of the roster")


def _check_facts(ctx: GenContext, truth: TruthOut, out: Output) -> None:
    """A facts override must be about the truth's suspects and methods, at a feasible depth."""
    if not isinstance(out, FactsOut):
        return
    roster = truth.roster
    records = {(s.kind, s.subject) for s in out.record_sources if s.subject_type == "suspect"}
    if records != {(s.record_kind, s.pos) for s in roster.suspects}:
        raise ValueError("the facts override must have a record for each of the truth's suspects")
    traces = {f.id[2:] for f in out.facts if f.id.startswith("h_")}
    if traces != {m.pos for m in roster.methods}:
        raise ValueError("the facts override must have a trace for each of the truth's methods")
    subject = {d.key: d.subject for d in ctx.pack.record_defs}
    located = {s.kind for s in out.record_sources if s.subject_type == "location"}
    if located != {k for k in roster.record_kinds if subject[k] == "location"}:
        raise ValueError(
            "the facts override must have a record source for each of the truth's location records"
        )
    expected = [(s.record_kind, "suspect", s.pos) for s in roster.suspects]
    expected += [(k, "location", "") for k in roster.record_kinds if subject[k] == "location"]
    found = [(s.kind, s.subject_type, s.subject or "") for s in out.record_sources]
    if sorted(found) != sorted(expected):
        raise ValueError(
            "the facts override must have each record source of the truth exactly once"
        )
    _check_fact_references(ctx, roster, out)
    if any(f.id.startswith("c_") for f in out.facts) != (out.depth == 2):
        raise ValueError("the facts override has keys only at depth 2")
    location_records = sum(s.subject_type == "location" for s in out.record_sources)
    if out.depth not in feasible_depths(ctx.spec, location_records):
        raise ValueError(
            f"the facts override has depth {out.depth}, which the {ctx.preset!r} preset cannot use"
        )


def _check_fact_references(ctx: GenContext, roster: RosterOut, out: FactsOut) -> None:
    """Every fact id is unique and every reference in a fact points into the case."""
    ids = [f.id for f in out.facts]
    if len(set(ids)) != len(ids):
        raise ValueError("the facts override has a fact id more than once")
    candidates = {
        "who": {s.pos for s in roster.suspects},
        "how": {m.pos for m in roster.methods},
        "why": {v.pos for v in roster.motives},
    }
    places = {loc.pos for loc in roster.locations}
    for fact in out.facts:
        for field, refs in (
            ("exposed_by", fact.exposed_by),
            ("requires", fact.requires),
            ("apart_from", (fact.apart_from,) if fact.apart_from else ()),
        ):
            for ref in refs:
                if ref not in ids:
                    raise ValueError(f"the facts override: {fact.id} has {field} {ref!r}, no fact")
        for effect in fact.effects:
            if effect.candidate not in candidates.get(effect.axis, set()):
                raise ValueError(
                    f"the facts override: {fact.id} has an effect on {effect.candidate!r}, "
                    f"not a candidate of the {effect.axis!r} axis of the truth"
                )
        claim = fact.claim
        if claim and (claim.slot not in range(ctx.spec.slots) or claim.place not in places):
            raise ValueError(
                f"the facts override: {fact.id} claims slot {claim.slot} at {claim.place!r}, "
                "outside the case"
            )


def _check_placement(ctx: GenContext, truth: TruthOut, out: FactsOut, placed: Output) -> None:
    """A placement override must place exactly the search facts, within the cap, with no empty
    location, and give every record source a subject its record kind can be about."""
    if not isinstance(placed, PlacementOut):
        return
    kind_of = {loc.pos: loc.kind for loc in truth.roster.locations}
    search = {f.id: f for f in out.facts if f.home.kind == "search"}
    ids = [p.fact for p in placed.search]
    if sorted(ids) != sorted(search):
        raise ValueError("the placement override must place each search fact exactly once")
    where = {p.fact: p.location for p in placed.search}
    if not set(where.values()) <= set(kind_of):
        raise ValueError("the placement override puts a fact at a location the roster lacks")
    for fact in search.values():
        if fact.place_kinds and kind_of[where[fact.id]] not in fact.place_kinds:
            raise ValueError(f"the placement override puts {fact.id} where its trace cannot be")
        if fact.apart_from and where[fact.apart_from] == where[fact.id]:
            raise ValueError(f"the placement override puts {fact.id} beside {fact.apart_from}")
    load = {loc: sum(1 for w in where.values() if w == loc) for loc in kind_of}
    if max(load.values()) > ctx.spec.source_cap or min(load.values()) == 0:
        raise ValueError("the placement override overfills or leaves a location empty")
    records = {d.key: d for d in ctx.pack.record_defs}
    if any(r.subject_type not in ("suspect", "location") for r in placed.record_sources):
        raise ValueError(
            "the placement override has a record source about neither a suspect nor a location"
        )
    expected = sorted(
        (s.kind, s.subject_type, s.subject or "") for s in out.record_sources if s.subject
    )
    got = sorted(
        (r.kind, r.subject_type, r.subject)
        for r in placed.record_sources
        if r.subject_type == "suspect"
    )
    if got != expected:
        raise ValueError("the placement override must keep the suspects' record sources")
    wanted = sorted(s.kind for s in out.record_sources if s.subject is None)
    located = [r for r in placed.record_sources if r.subject_type == "location"]
    if sorted(r.kind for r in located) != wanted:
        raise ValueError("the placement override must have a source for each location record")
    for record in located:
        if record.subject not in kind_of or kind_of[record.subject] not in (
            records[record.kind].location_kinds
        ):
            raise ValueError(f"the placement override makes {record.kind!r} about a bad location")


def _check_overrides(ctx: GenContext, override: Mapping[str, Output]) -> None:
    """Refuse an override that does not fit the spec, or a truth about other people."""
    roster, truth, timeline = (override.get(s) for s in ("roster", "truth", "timeline"))
    if isinstance(roster, RosterOut):
        _check_roster(ctx, "roster", roster)
        _check_roster_kinds(ctx, "roster", roster)
    if isinstance(truth, TruthOut):
        _check_roster(ctx, "truth", truth.roster)
        _check_roster_kinds(ctx, "truth", truth.roster)
        if isinstance(roster, RosterOut) and {s.name for s in roster.suspects} != {
            s.name for s in truth.roster.suspects
        }:
            raise ValueError("the truth override must be about the same people as the roster")
    if isinstance(timeline, TimelineOut):
        _check_timeline(ctx, timeline)


# `_need` exists only to narrow the type of a stage output for mypy.
def _need[T: Output](outputs: dict[str, Output], stage: str, kind: type[T]) -> T:
    found = outputs[stage]
    if not isinstance(found, kind):
        raise TypeError(f"the {stage} output must be a {kind.__name__}, not {type(found).__name__}")
    return found
