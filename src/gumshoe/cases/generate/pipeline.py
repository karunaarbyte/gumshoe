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

from collections.abc import Callable, Iterable, Mapping, Sequence
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
from gumshoe.cases.generate.skin import template_skin
from gumshoe.cases.generate.skin_catalogue import SkinIssue
from gumshoe.cases.generate.skin_lint import lint as skin_lint
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.generate.structure import need, run_stage
from gumshoe.cases.generate.trace import Attempt, CaseGenerationError, GenerationTrace
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import skin_hash
from gumshoe.cases.validate.report import Issue, Profile, Report, Severity
from gumshoe.cases.validate.runner import validate

BUDGET = 20  # attempts (validator calls and stage failures) before the run gives up
RETRIES = 5  # restarts of one stage before the stage before it is restarted instead
UNFIXABLE = (FixStage.PACK, FixStage.NONE, FixStage.ASSEMBLE)

Runner = Callable[[GenContext, str, Mapping[str, Output], int], Output]
Validator = Callable[[Case, Pack | None, Profile], Report]
Skin = Callable[[GenContext, Stream, Case], Case]
Lint = Callable[[Case, Pack], Sequence[SkinIssue]]


def identity_skin(ctx: GenContext, stream: Stream, case: Case) -> Case:
    """A skin stage that adds no wording, so the case stays skeleton-only (tests)."""
    return case


def no_lint(case: Case, pack: Pack) -> Sequence[SkinIssue]:
    """A text lint that finds nothing (tests that inject a skin of their own)."""
    return ()


@dataclass(frozen=True)
class _Verdict:
    """Why an attempt failed: its codes, the stage that fixes it (empty when none can), the codes
    no stage can fix, the validator's report (None for a text lint or a stage error) and a
    detail line."""

    codes: tuple[str, ...]
    fix: str
    unfixable: list[str]
    report: Report | None
    detail: str = ""


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
    """The bookkeeping fields, which no rule reads."""
    pack = ctx.pack
    code = ("c", ctx.seed, ctx.preset, pack.id, pack.skeleton_hash(), ctx.spec_hash)
    return case.model_copy(
        update={
            "id": make_id(*code, SKELETON_ALGO_VERSION, generator_version()),
            "seed": ctx.seed,
            "generator_version": generator_version(),
            "skeleton_algo_version": SKELETON_ALGO_VERSION,
            "pack_versions": (("skeleton_rev", pack.skeleton_rev), ("skin_rev", pack.skin_rev)),
            "attempt": attempts,
            "stage_attempts": retry.counters(),
            "theme": pack.id,
            "skin_rev": pack.skin_rev,
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
        lint: Lint,
    ) -> None:
        self.ctx, self.budget = ctx, budget
        self.runner, self.validator, self.skin, self.lint = runner, validator, skin, lint
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

    def _verdict(self, case: Case) -> "_Verdict | None":
        """None when the case is good: the strict validator first, then the text lint (one
        attempt judges both)."""
        report = self.validator(case, self.ctx.pack, Profile.STRICT)
        errors = [i for i in report.issues if i.severity is Severity.ERROR]
        if errors:
            return self._from_report(report, errors)
        try:
            issues = list(self.lint(case, self.ctx.pack))
        except GenerationError as error:  # a text the lint cannot check is the skin's to redraw
            detail = str(error) or type(error).__name__
            return _Verdict(("STAGE_ERROR",), "skin", [], None, detail)
        if issues:
            codes = tuple(sorted({i.code for i in issues}))
            return _Verdict(
                codes, "skin", [], None, "; ".join(f"{i.path}: {i.message}" for i in issues[:3])
            )
        return None

    @staticmethod
    def _from_report(report: Report, errors: list[Issue]) -> "_Verdict":
        codes = tuple(sorted({i.code for i in errors}))
        unfixable = sorted({i.code for i in errors if i.fix_stage in UNFIXABLE})
        fix = "" if unfixable else earliest(i.fix_stage for i in errors)
        return _Verdict(codes, fix, unfixable, report)

    def _after_stage_error(self, failed: _StageFailed) -> "_Verdict":
        """A stage raised. If it was the skin, the skeleton may be at fault (a skin cannot render
        a case that has no place for its text) and the validator names the real cause: ask it."""
        detail = str(failed.error) or type(failed.error).__name__
        if failed.stage == "skin" and self.assembled is not None:
            report = self.validator(self.assembled, self.ctx.pack, Profile.STRICT)
            errors = [i for i in report.issues if i.severity is Severity.ERROR]
            if errors:
                return self._from_report(report, errors)
        return _Verdict(("STAGE_ERROR",), failed.stage, [], None, detail)

    def run(self) -> tuple[Case, GenerationTrace]:
        start = 0
        while True:
            used = self.retry.counters()
            try:
                case = self.build(start)
            except _StageFailed as failed:
                verdict: _Verdict | None = self._after_stage_error(failed)
            else:
                verdict = self._verdict(case)
                if verdict is None:
                    self.attempts.append(
                        Attempt(len(self.attempts) + 1, PIPELINE[start], used, (), None)
                    )
                    return _stamp(self.ctx, case, self.retry, len(self.attempts)), self.trace()
            assert verdict is not None
            fix, unfixable = verdict.fix, verdict.unfixable
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
            self.attempts.append(
                Attempt(number, PIPELINE[start], used, verdict.codes, restart, verdict.detail)
            )
            if restart is None:
                said = f"the {fix} stage failed: " if verdict.codes == ("STAGE_ERROR",) else ""
                last = f" (the last failure: {said}{verdict.detail})" if verdict.detail else ""
                raise CaseGenerationError(f"{reason}{last}", self.trace(), verdict.report)
            start = PIPELINE.index(restart)


def run_pipeline(
    ctx: GenContext,
    *,
    counters: Mapping[str, int] | None = None,
    budget: int = BUDGET,
    runner: Runner = run_stage,
    validator: Validator | None = None,
    skin: Skin = template_skin,
    lint: Lint = skin_lint,
) -> tuple[Case, GenerationTrace]:
    """Generate the case, retrying as the design says. `counters` starts the stages at given
    stream counters (a replay of a stored case); the other arguments let tests inject faults.
    The default validator is the strict one with the context's presets."""
    if budget < 1:
        raise ValueError(f"the budget must be at least one attempt, not {budget}")
    check = validator or partial(validate, presets=ctx.presets)
    return _Run(ctx, counters, budget, runner, check, skin, lint).run()
