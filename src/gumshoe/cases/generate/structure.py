"""The fold over the structural stages. 2d-3's pipeline replaces it with the retry controller;
until then every stage runs once, with stream counter 0."""

from collections.abc import Mapping

from gumshoe.cases.generate import roster, timeline, truth
from gumshoe.cases.generate.gen_context import STAGES, GenContext
from gumshoe.cases.generate.outputs import Output, RosterOut, TimelineOut, TruthOut

OUTPUT_TYPES: dict[str, type[Output]] = {
    "roster": RosterOut,
    "truth": TruthOut,
    "timeline": TimelineOut,
}


def run_structure(
    ctx: GenContext,
    upto: str = "timeline",
    override: Mapping[str, Output] | None = None,
) -> dict[str, Output]:
    """Run the stages in order up to and including `upto`. An override replaces that stage's
    output instead of running it, and the later stages run on top of it. An override for a stage
    after `upto` is validated but ignored. A truth override replaces the roster entry by its own
    roster (unless the roster is itself overridden), so the returned dict stays consistent."""
    override = override or {}
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
    out: dict[str, Output] = {}
    for stage in STAGES:
        if stage in override:
            out[stage] = override[stage]
        elif stage == "roster":
            out[stage] = roster.run(ctx, ctx.stream(stage))
        elif stage == "truth":
            out[stage] = truth.run(ctx, ctx.stream(stage), _need(out, "roster", RosterOut))
        else:
            out[stage] = timeline.run(ctx, ctx.stream(stage), _need(out, "truth", TruthOut))
        if stage == "truth" and stage in override and "roster" not in override:
            out["roster"] = _need(out, "truth", TruthOut).roster
        if stage == upto:
            break
    return out


# `_need` exists only to narrow the type of a stage output for mypy.
def _need[T: Output](outputs: dict[str, Output], stage: str, kind: type[T]) -> T:
    found = outputs[stage]
    if not isinstance(found, kind):
        raise TypeError(f"the {stage} output must be a {kind.__name__}, not {type(found).__name__}")
    return found
