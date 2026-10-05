"""Developer-only generator replay. Never reachable from a player surface."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from gumshoe.cases.generate.api import generate_traced
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
from gumshoe.cases.generate.trace import CaseGenerationError, GenerationTrace
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
    counters: Mapping[str, int] | None = None,
) -> dict[str, Output]:
    """The stage outputs for a seed up to `upto`. `override={stage: output}` replaces a stage's
    output and re-runs only the later stages on it (to see what a different roster would do).
    `counters` gives each stage's stream counter (`Case.stage_attempts` of a retried case)."""
    ctx = GenContext.of(pack, seed, preset, presets)
    return run_structure(ctx, upto, override, counters)


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


@dataclass(frozen=True)
class SmokeReport:
    """How `generate` did over a run of seeds: attempts per case and which codes caused retries."""

    preset: str
    attempts: tuple[tuple[int, int], ...]  # (attempts used, number of cases), ascending
    codes: tuple[tuple[str, int], ...]  # (error code, failed attempts that reported it)
    errors: tuple[tuple[int, str], ...]  # (seed, why) for every seed that gave no case

    @property
    def cases(self) -> int:
        return sum(count for _, count in self.attempts)

    @property
    def mean_attempts(self) -> float:
        return sum(used * count for used, count in self.attempts) / max(self.cases, 1)

    @property
    def max_attempts(self) -> int:
        return max((used for used, _ in self.attempts), default=0)

    @property
    def ok(self) -> bool:
        """The pack-load smoke criterion: some case was made, no seed failed, mean attempts <= 2
        and max <= 10."""
        return (
            self.cases > 0
            and not self.errors
            and self.mean_attempts <= 2
            and self.max_attempts <= 10
        )

    def lines(self) -> list[str]:
        out = [
            f"{self.preset}: {self.cases} cases, attempts mean {self.mean_attempts:.2f} "
            f"max {self.max_attempts}, {len(self.errors)} failed"
        ]
        out += [f"  {used} attempt(s): {count} case(s)" for used, count in self.attempts]
        out += [f"  {code}: {count}" for code, count in self.codes]
        out += [f"  seed {seed}: {why}" for seed, why in self.errors]
        if self.cases == 0 and not self.errors:
            out.append("  no case was made")
        return out


def smoke(
    pack: Pack,
    preset: str,
    seeds: Iterable[int],
    presets: Mapping[str, PresetDef] = PRESETS,
) -> SmokeReport:
    """Generate a case for every seed and report the attempts it took. A seed that gives no case
    is reported, not raised; the pack must have passed the pack checks (`load_builtin_pack`)."""
    used: Counter[int] = Counter()
    codes: Counter[str] = Counter()
    errors: list[tuple[int, str]] = []

    def count(trace: GenerationTrace) -> None:
        for attempt in trace.attempts:
            codes.update(attempt.codes)

    for seed in seeds:
        try:
            _, trace = generate_traced(seed, preset, pack, presets)
        except CaseGenerationError as error:
            errors.append((seed, str(error)))
            count(error.trace)
            continue
        used[len(trace.attempts)] += 1
        count(trace)
    return SmokeReport(
        preset, tuple(sorted(used.items())), tuple(sorted(codes.items())), tuple(errors)
    )
