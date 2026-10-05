"""Developer-only generator replay. Never reachable from a player surface."""

from collections.abc import Mapping

from gumshoe.cases.generate.assemble import build_case
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    FactsOut,
    GatingOut,
    Output,
    PlacementOut,
    TimelineOut,
    TruthOut,
)
from gumshoe.cases.generate.structure import need, run_structure
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef


def replay(
    seed: int,
    preset: str,
    pack: Pack,
    upto: str | None = None,
    override: Mapping[str, Output] | None = None,
    presets: Mapping[str, PresetDef] = PRESETS,
) -> dict[str, Output]:
    """The stage outputs for a seed up to `upto`. `override={stage: output}` replaces a stage's
    output and re-runs only the later stages on it (to see what a different roster would do)."""
    ctx = GenContext.of(pack, seed, preset, presets)
    return run_structure(ctx, upto, override)


def skeleton(
    seed: int,
    preset: str,
    pack: Pack,
    override: Mapping[str, Output] | None = None,
    presets: Mapping[str, PresetDef] = PRESETS,
) -> Case:
    """The skeleton-only case every stage gives for a seed (blank skin, neutral ids, so the
    culprit is `s0`: a spoiler by construction). `override` works as in `replay`."""
    ctx = GenContext.of(pack, seed, preset, presets)
    out = run_structure(ctx, None, override)
    return build_case(
        ctx,
        need(out, "truth", TruthOut),
        need(out, "timeline", TimelineOut),
        need(out, "facts", FactsOut),
        need(out, "placement", PlacementOut),
        need(out, "gating", GatingOut),
    )
