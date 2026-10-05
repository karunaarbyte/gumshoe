"""Developer-only generator replay. Never reachable from a player surface."""

from collections.abc import Mapping

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import Output
from gumshoe.cases.generate.structure import run_structure
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
