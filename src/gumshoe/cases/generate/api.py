"""The public face of the generator: `generate(seed, preset, pack) -> Case`.

A case is a pure function of the seed, the preset, the pack and the code versions, so a shared
seed is the whole code. Nothing here reads a clock, a file or the global random generator."""

from collections.abc import Mapping, Sequence

from gumshoe.cases.generate.assemble import generator_version
from gumshoe.cases.generate.gen_context import PIPELINE, SKELETON_ALGO_VERSION, GenContext
from gumshoe.cases.generate.pipeline import run_pipeline
from gumshoe.cases.generate.trace import CaseGenerationError, GenerationTrace
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef

__all__ = [
    "CaseGenerationError",
    "GenerationTrace",
    "VersionMismatch",
    "generate",
    "generate_traced",
    "regenerate",
]


class VersionMismatch(ValueError):
    """A stored case was made by other code than this: its seed cannot be replayed here."""


def generate_traced(
    seed: int, preset: str, pack: Pack, presets: Mapping[str, PresetDef] = PRESETS
) -> tuple[Case, GenerationTrace]:
    """The case for a seed and every attempt it took. Raises `UnsupportedPreset` for a preset the
    pack cannot host and `CaseGenerationError` when no valid case comes out."""
    return run_pipeline(GenContext.of(pack, seed, preset, presets))


def generate(
    seed: int, preset: str, pack: Pack, presets: Mapping[str, PresetDef] = PRESETS
) -> Case:
    return generate_traced(seed, preset, pack, presets)[0]


def regenerate(case: Case, pack: Pack, presets: Mapping[str, PresetDef] = PRESETS) -> Case:
    """Rebuild a generated case from its stored seed and stage counters: each stage runs once and
    the validator once, however many attempts the original took. Refuses a case made by other
    code or another pack (`VersionMismatch`); if that one pass does not validate (the validator
    changed since the case was made) it raises `CaseGenerationError` instead of drawing a
    different case. The result equals the original except `attempt`."""
    if case.seed is None or case.pack_ref is None:
        raise VersionMismatch("the case records no seed or pack: it was not generated")
    if case.skeleton_algo_version != SKELETON_ALGO_VERSION:
        raise VersionMismatch(
            f"the case has skeleton algorithm {case.skeleton_algo_version}, "
            f"this code has {SKELETON_ALGO_VERSION}"
        )
    if case.generator_version != generator_version():
        raise VersionMismatch(
            f"the case was made by {case.generator_version}, this code is {generator_version()}"
        )
    if (case.pack_ref.id, case.pack_ref.skeleton_hash) != (pack.id, pack.skeleton_hash()):
        raise VersionMismatch(f"the case was made for another version of the pack {pack.id!r}")
    counters: Sequence[int] = case.stage_attempts
    if len(counters) != len(PIPELINE):
        raise VersionMismatch(
            f"the case stores {len(counters)} stage counters, not {len(PIPELINE)}"
        )
    ctx = GenContext.of(pack, case.seed, case.spec.preset, presets)
    if ctx.spec != case.spec:
        raise VersionMismatch("the case was made for another spec: the preset tables differ")
    stored = dict(zip(PIPELINE, counters, strict=True))
    return run_pipeline(ctx, counters=stored, budget=1)[0]
