"""The pipeline: every stage in order, the strict validator, and the retry controller.

Stage order is `roster < truth < timeline < facts < placement < gating < assemble < skin`. Each
stage has a stream counter `n[stage]` (stage streams are keyed by it, never by the attempt) and a
retry count `k[stage]`. An attempt is one strict-validator call. The design makes a case valid by
construction, so on the castle the controller is a net that is never used; its rules are the
overview's section 2.3:

1. An error whose `fix_stage` is `pack`, `none` or `assemble` is a bug or a bad pack: stop.
2. Otherwise restart from the earliest `fix_stage` of the errors, with `k` of that stage + 1. A
   stage that raises `GenerationError` fails the same way with that stage as its fix stage: a seed
   can be unlucky for a pack that passed its checks, and a new stream cures that.
3. A stage retried more than `RETRIES` times resets its `k` and the stage before it is retried
   instead; past `roster` there is nowhere to go and the run stops.
4. Every stage from the restart stage on gets a new counter and the later ones a fresh `k`.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import partial

from gumshoe.cases.core.enums import FixStage
from gumshoe.cases.core.ids import make_id
from gumshoe.cases.generate.assemble import assemble, generator_version
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import (
    PIPELINE,
    SKELETON_ALGO_VERSION,
    GenContext,
    check_counters,
)
from gumshoe.cases.generate.outputs import (
    FactsOut,
    GatingOut,
    Output,
    PlacementOut,
    TimelineOut,
    TruthOut,
)
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.generate.structure import need, run_stage
from gumshoe.cases.generate.trace import Attempt, CaseGenerationError, GenerationTrace
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import skin_hash
from gumshoe.cases.validate.report import Profile, Report, Severity
from gumshoe.cases.validate.runner import validate

BUDGET = 20  # attempts (validator calls and stage failures) before the run gives up
RETRIES = 5  # restarts of one stage before the stage before it is restarted instead
UNFIXABLE = (FixStage.PACK, FixStage.NONE, FixStage.ASSEMBLE)

Runner = Callable[[GenContext, str, Mapping[str, Output], int], Output]
Validator = Callable[[Case, Pack | None, Profile], Report]
Skin = Callable[[GenContext, Stream, Case], Case]


def identity_skin(ctx: GenContext, stream: Stream, case: Case) -> Case:
    """The skin stage until 2d-3b: no wording, so the case stays skeleton-only."""
    return case


class Exhausted(Exception):
    """Every stage down to `roster` has used up its retries."""


@dataclass
class Retry:
    """The counters of the retry design: `n` per stage (stream counters), `k` per stage."""

    n: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PIPELINE, 0))
    k: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PIPELINE, 0))

    def counters(self) -> tuple[int, ...]:
        return tuple(self.n[stage] for stage in PIPELINE)

    def fail(self, stage: str) -> str:
        """Record a failure whose earliest fixing stage is `stage`; return the stage to restart
        from (rules 2 to 4). Raises `Exhausted` when `roster` has no retries left."""
        i = PIPELINE.index(stage)
        self.k[PIPELINE[i]] += 1
        while self.k[PIPELINE[i]] > RETRIES:
            if i == 0:
                raise Exhausted
            i -= 1
            self.k[PIPELINE[i]] += 1
        for later in PIPELINE[i:]:
            self.n[later] += 1
        for later in PIPELINE[i + 1 :]:
            self.k[later] = 0
        return PIPELINE[i]


def earliest(stages: Iterable[FixStage]) -> str:
    """The first of these fix stages in pipeline order."""
    return min((s.value for s in stages), key=PIPELINE.index)


def _stamp(ctx: GenContext, case: Case, retry: Retry, attempts: int) -> Case:
    """The bookkeeping fields, which no rule reads. `skin_rev` is 0: there is no skin yet."""
    pack = ctx.pack
    code = ("c", ctx.seed, ctx.preset, pack.id, pack.skeleton_hash(), ctx.spec_hash)
    return case.model_copy(
        update={
            "id": make_id(*code, SKELETON_ALGO_VERSION, generator_version()),
            "seed": ctx.seed,
            "generator_version": generator_version(),
            "skeleton_algo_version": SKELETON_ALGO_VERSION,
            "pack_versions": (("skeleton_rev", pack.skeleton_rev),),
            "attempt": attempts,
            "stage_attempts": retry.counters(),
            "theme": pack.id,
            "skin_rev": 0,
            "skin_hash": skin_hash(case),
        }
    )


class _StageFailed(Exception):
    """A stage raised `GenerationError` (the run turns it into a failed attempt)."""

    def __init__(self, stage: str, error: GenerationError) -> None:
        super().__init__(f"the {stage} stage failed: {error}")
        self.stage, self.error = stage, error


class _Run:
    """One generation run: the stage outputs so far, the retry state and the attempts made."""

    def __init__(
        self,
        ctx: GenContext,
        counters: Mapping[str, int] | None,
        budget: int,
        runner: Runner,
        validator: Validator,
        skin: Skin,
    ) -> None:
        self.ctx, self.budget = ctx, budget
        self.runner, self.validator, self.skin = runner, validator, skin
        self.retry = Retry()
        self.retry.n.update(check_counters(counters))
        self.out: dict[str, Output] = {}
        self.assembled: Case | None = None
        self.attempts: list[Attempt] = []

    def trace(self) -> GenerationTrace:
        return GenerationTrace(tuple(self.attempts))

    def build(self, start: int) -> Case:
        """Run the stages from `PIPELINE[start]` on, each with its current stream counter, and
        return the skinned case. The outputs of the stages before `start` are kept."""
        ctx, n = self.ctx, self.retry.n
        case: Case | None = None
        for stage in PIPELINE[start:]:
            try:
                if stage == "assemble":
                    self.assembled = assemble(
                        ctx,
                        need(self.out, "truth", TruthOut),
                        need(self.out, "timeline", TimelineOut),
                        need(self.out, "facts", FactsOut),
                        need(self.out, "placement", PlacementOut),
                        need(self.out, "gating", GatingOut),
                    )
                elif stage == "skin":
                    if self.assembled is None:
                        raise GenerationError("the skin stage ran before assemble")
                    case = self.skin(ctx, ctx.stream(stage, n[stage]), self.assembled)
                else:
                    self.out[stage] = self.runner(ctx, stage, self.out, n[stage])
            except GenerationError as error:
                raise _StageFailed(stage, error) from error
        if case is None:  # skin is the last stage, so a build always reaches it
            raise GenerationError("the pipeline ended without a skinned case")
        return case

    def run(self) -> tuple[Case, GenerationTrace]:
        start = 0
        while True:
            used = self.retry.counters()
            report: Report | None = None
            codes: tuple[str, ...]
            detail, unfixable = "", None
            try:
                case = self.build(start)
            except _StageFailed as failed:
                codes, fix = ("STAGE_ERROR",), failed.stage
                detail = str(failed.error) or type(failed.error).__name__
            else:
                report = self.validator(case, self.ctx.pack, Profile.STRICT)
                errors = [i for i in report.issues if i.severity is Severity.ERROR]
                if not errors:
                    self.attempts.append(
                        Attempt(len(self.attempts) + 1, PIPELINE[start], used, (), None)
                    )
                    return _stamp(self.ctx, case, self.retry, len(self.attempts)), self.trace()
                codes = tuple(sorted({i.code for i in errors}))
                unfixable = sorted({i.code for i in errors if i.fix_stage in UNFIXABLE})
                fix = "" if unfixable else earliest(i.fix_stage for i in errors)
            reason = f"no stage can fix {', '.join(unfixable)}" if unfixable else None
            if reason is None and len(self.attempts) + 1 >= self.budget:
                noun = "attempt" if self.budget == 1 else "attempts"
                reason = f"the budget of {self.budget} {noun} ran out"
            restart = None
            if reason is None:
                try:
                    restart = self.retry.fail(fix)
                except Exhausted:
                    reason = "every stage used up its retries"
            number = len(self.attempts) + 1
            self.attempts.append(Attempt(number, PIPELINE[start], used, codes, restart, detail))
            if restart is None:
                last = f" (the last failure: the {fix} stage failed: {detail})" if detail else ""
                raise CaseGenerationError(f"{reason}{last}", self.trace(), report)
            start = PIPELINE.index(restart)


def run_pipeline(
    ctx: GenContext,
    *,
    counters: Mapping[str, int] | None = None,
    budget: int = BUDGET,
    runner: Runner = run_stage,
    validator: Validator | None = None,
    skin: Skin = identity_skin,
) -> tuple[Case, GenerationTrace]:
    """Generate the case, retrying as the design says. `counters` starts the stages at given
    stream counters (a replay of a stored case); the other arguments let tests inject faults.
    The default validator is the strict one with the context's presets."""
    if budget < 1:
        raise ValueError(f"the budget must be at least one attempt, not {budget}")
    check = validator or partial(validate, presets=ctx.presets)
    return _Run(ctx, counters, budget, runner, check, skin).run()
