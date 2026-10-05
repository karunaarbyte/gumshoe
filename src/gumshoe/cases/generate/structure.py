"""The fold over the structural stages. 2d-3's pipeline replaces it with the retry controller;
until then every stage runs once, with stream counter 0."""

from collections.abc import Mapping

from gumshoe.cases.generate import facts, roster, timeline, truth
from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.generate.gen_context import STAGES, GenContext
from gumshoe.cases.generate.outputs import FactsOut, Output, RosterOut, TimelineOut, TruthOut

OUTPUT_TYPES: dict[str, type[Output]] = {
    "roster": RosterOut,
    "truth": TruthOut,
    "timeline": TimelineOut,
    "facts": FactsOut,
}


def run_structure(
    ctx: GenContext,
    upto: str | None = None,
    override: Mapping[str, Output] | None = None,
) -> dict[str, Output]:
    """Run the stages in order up to and including `upto` (the last stage when None). An override
    replaces that stage's output instead of running it, and the later stages run on top of it.
    An override for a stage after `upto` is type- and size-checked but otherwise ignored (the
    checks that need a computed truth, the timeline's rows and the facts, run when the loop
    reaches that stage). A truth override replaces the roster entry by its own roster (unless the
    roster is itself overridden), so the returned dict stays consistent: with a truth override
    and no roster override the returned `roster` entry is the truth's (reordered) roster, not the
    pre-truth roster. Overrides are checked against `ctx.spec` and each other."""
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
        if stage in override:
            out[stage] = override[stage]
        elif stage == "roster":
            out[stage] = roster.run(ctx, ctx.stream(stage))
        elif stage == "truth":
            out[stage] = truth.run(ctx, ctx.stream(stage), _need(out, "roster", RosterOut))
        elif stage == "timeline":
            out[stage] = timeline.run(ctx, ctx.stream(stage), _need(out, "truth", TruthOut))
        else:
            out[stage] = facts.run(
                ctx,
                ctx.stream(stage),
                _need(out, "truth", TruthOut),
                _need(out, "timeline", TimelineOut),
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


def _check_timeline(ctx: GenContext, timeline: TimelineOut) -> None:
    spec = ctx.spec
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
    if isinstance(timeline, TimelineOut) and len(timeline.rows) != len(truth.roster.suspects):
        raise ValueError(
            f"the timeline override has {len(timeline.rows)} rows for "
            f"{len(truth.roster.suspects)} suspects"
        )


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
    location_records = sum(s.subject_type == "location" for s in out.record_sources)
    if out.depth not in feasible_depths(ctx.spec, location_records):
        raise ValueError(
            f"the facts override has depth {out.depth}, which the {ctx.preset!r} preset cannot use"
        )


def _check_overrides(ctx: GenContext, override: Mapping[str, Output]) -> None:
    """Refuse an override that does not fit the spec, or a truth about other people."""
    roster, truth, timeline = (override.get(s) for s in ("roster", "truth", "timeline"))
    if isinstance(roster, RosterOut):
        _check_roster(ctx, "roster", roster)
    if isinstance(truth, TruthOut):
        _check_roster(ctx, "truth", truth.roster)
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
