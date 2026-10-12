from dataclasses import replace

import pytest

from gumshoe.cases.generate.api import VersionMismatch, generate, generate_traced, regenerate
from gumshoe.cases.generate.assemble import generator_version
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import PIPELINE, SKELETON_ALGO_VERSION, GenContext
from gumshoe.cases.generate.outputs import GatingOut
from gumshoe.cases.generate.pipeline import run_pipeline
from gumshoe.cases.generate.skin_catalogue import make
from gumshoe.cases.generate.structure import run_stage
from gumshoe.cases.generate.trace import CaseGenerationError
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Start
from gumshoe.cases.model.serialize import skeleton_digest
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Profile, Report, Severity
from gumshoe.cases.validate.runner import validate
from tests.generate import retry_model
from tests.generate.helpers import PRESET_NAMES, castle

FACTS_CODE, ROSTER_CODE, GATING_CODE, PLACEMENT_CODE = (
    "NO_POSITIVE_EVIDENCE",
    "LABEL_DUPLICATE",
    "DEPTH_RANGE",
    "ACTIONS_RANGE",
)


def fake_report(case: Case, codes: list[str]) -> Report:
    """A report holding exactly these codes (any catalogue code, whatever the case)."""
    ctx = Ctx(case=case, pack=None, profile=Profile.STRICT)
    issues = sorted((ctx.issue(code) for code in codes), key=lambda issue: issue.sort_key())
    return Report(Profile.STRICT, tuple(issues))


def scripted(script: list[list[str]], *, then_real: bool = True):
    """A validator that answers the first calls from `script` (a list of code lists) and then
    either validates for real or keeps repeating the last answer."""
    calls: list[int] = []

    def validator(case, pack, profile):
        calls.append(1)
        if len(calls) <= len(script):
            return fake_report(case, script[len(calls) - 1])
        return validate(case, pack, profile) if then_real else fake_report(case, script[-1])

    validator.calls = calls  # type: ignore[attr-defined]
    return validator


def recording(log: list[tuple[str, int]]):
    def runner(ctx, stage, out, counter):
        log.append((stage, counter))
        return run_stage(ctx, stage, out, counter)

    return runner


def ctx_of(seed=3, preset="standard") -> GenContext:
    return GenContext.of(castle(), seed, preset)


# A clean run


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_seed_is_made_in_one_attempt_by_construction(preset):
    pack = castle()
    for seed in range(200):
        case, trace = generate_traced(seed, preset, pack)
        attempt = trace.attempts[0]
        assert len(trace.attempts) == 1 and attempt.codes == () and attempt.restart is None, seed
        assert attempt.counters == (0,) * 8 and case.attempt == 1


def test_the_case_carries_its_bookkeeping():
    pack = castle()
    case = generate(6, "standard", pack)
    assert case.seed == 6 and case.stage_attempts == (0,) * len(PIPELINE) and case.attempt == 1
    assert case.generator_version == generator_version()
    assert [part.split("=")[0] for part in generator_version().split(",")] == list(PIPELINE)
    assert case.skeleton_algo_version == SKELETON_ALGO_VERSION
    assert case.pack_versions == (("skeleton_rev", pack.skeleton_rev),)
    assert case.theme == pack.id and case.skin_rev == 0 and case.skin_hash
    assert case.pack_ref is not None and case.pack_ref.skeleton_hash == pack.skeleton_hash()
    others = {generate(s, p, pack).id for s in range(3) for p in PRESET_NAMES}
    assert case.id not in others and len(others) == 9


def test_generation_is_deterministic_and_depends_on_the_seed():
    pack = castle()
    a, b = generate(11, "long", pack), generate(11, "long", pack)
    assert a == b and skeleton_digest(a) == skeleton_digest(b)
    assert skeleton_digest(generate(12, "long", pack)) != skeleton_digest(a)


# The controller restarts where the design says


def test_a_facts_failure_reruns_facts_and_everything_after_it_only():
    ctx, skins = ctx_of(), []
    log: list[tuple[str, int]] = []

    def skin(ctx, stream, case):
        skins.append(stream)
        return case

    case, trace = run_pipeline(
        ctx, runner=recording(log), validator=scripted([[FACTS_CODE]]), skin=skin
    )
    first = [(s, 0) for s in PIPELINE[:6]]
    assert log == first + [("facts", 1), ("placement", 1), ("gating", 1)]
    assert len(skins) == 2  # skin follows assemble on every attempt
    one, two = trace.attempts
    assert (one.number, one.first_stage, one.counters) == (1, "roster", (0,) * 8)
    assert (one.codes, one.restart) == ((FACTS_CODE,), "facts")
    assert (two.number, two.first_stage, two.counters) == (2, "facts", (0, 0, 0, 1, 1, 1, 1, 1))
    assert (two.codes, two.restart) == ((), None)
    assert case.attempt == 2 and case.stage_attempts == (0, 0, 0, 1, 1, 1, 1, 1)


def test_the_earliest_stage_among_the_errors_is_restarted():
    log: list[tuple[str, int]] = []
    _, trace = run_pipeline(
        ctx_of(), runner=recording(log), validator=scripted([[GATING_CODE, ROSTER_CODE]])
    )
    assert trace.attempts[0].restart == "roster"
    assert log[-6:] == [(s, 1) for s in PIPELINE[:6]]
    assert trace.attempts[0].codes == tuple(sorted([GATING_CODE, ROSTER_CODE]))


@pytest.mark.parametrize("code", [FACTS_CODE, "PACK_MISMATCH"])
def test_a_warning_is_not_a_reason_to_retry_or_to_stop(code):
    def validator(case, pack, profile):
        report = fake_report(case, [code])
        return replace(
            report, issues=tuple(replace(i, severity=Severity.WARNING) for i in report.issues)
        )

    _, trace = run_pipeline(ctx_of(), validator=validator)
    assert len(trace.attempts) == 1 and trace.attempts[0].codes == ()


def test_an_unfixable_warning_does_not_stop_a_run_that_can_still_retry():
    def mixed(case, pack, profile):  # a retryable error and a warning that no stage could fix
        report = fake_report(case, [FACTS_CODE, "PACK_MISMATCH"])
        return replace(
            report,
            issues=tuple(
                replace(i, severity=Severity.WARNING) if i.code == "PACK_MISMATCH" else i
                for i in report.issues
            ),
        )

    answers = [mixed, lambda case, pack, profile: fake_report(case, [])]
    _, trace = run_pipeline(ctx_of(), validator=lambda *args: answers.pop(0)(*args))
    assert [a.restart for a in trace.attempts] == ["facts", None]
    assert trace.attempts[0].codes == (FACTS_CODE,)


def test_a_retried_case_is_what_its_stored_counters_replay():
    pack = castle()
    ctx = ctx_of()
    case, _ = run_pipeline(ctx, validator=scripted([[FACTS_CODE], [PLACEMENT_CODE]]))
    assert case.attempt == 3 and case.stage_attempts == (0, 0, 0, 1, 2, 2, 2, 2)
    again = regenerate(case, pack)
    assert again.attempt == 1  # one pass of every stage and one validator call
    assert skeleton_digest(again) == skeleton_digest(case)
    assert again.model_copy(update={"attempt": case.attempt}) == case
    assert skeleton_digest(generate(3, "standard", pack)) != skeleton_digest(case)


def test_the_worked_retry_trace():
    """The table of the spec: what the controller does on a scripted run of failures."""
    script = [[ROSTER_CODE], [FACTS_CODE], [FACTS_CODE], [GATING_CODE, PLACEMENT_CODE], []]
    _, trace = run_pipeline(ctx_of(), validator=scripted(script, then_real=False))
    assert trace.lines() == [
        " 1 from roster    n=[0, 0, 0, 0, 0, 0, 0, 0] LABEL_DUPLICATE -> restart roster",
        " 2 from roster    n=[1, 1, 1, 1, 1, 1, 1, 1] NO_POSITIVE_EVIDENCE -> restart facts",
        " 3 from facts     n=[1, 1, 1, 2, 2, 2, 2, 2] NO_POSITIVE_EVIDENCE -> restart facts",
        " 4 from facts     n=[1, 1, 1, 3, 3, 3, 3, 3] "
        "ACTIONS_RANGE,DEPTH_RANGE -> restart placement",
        " 5 from placement n=[1, 1, 1, 3, 4, 4, 4, 4] ok",
    ]


def test_the_worked_retry_trace_with_an_escalation():
    """The ten-line table of the spec (section 5)."""
    script = [[FACTS_CODE]] * 7 + [[GATING_CODE]] * 2
    case, trace = run_pipeline(ctx_of(), validator=scripted(script), budget=50)
    assert trace.lines() == [
        " 1 from roster    n=[0, 0, 0, 0, 0, 0, 0, 0] NO_POSITIVE_EVIDENCE -> restart facts",
        " 2 from facts     n=[0, 0, 0, 1, 1, 1, 1, 1] NO_POSITIVE_EVIDENCE -> restart facts",
        " 3 from facts     n=[0, 0, 0, 2, 2, 2, 2, 2] NO_POSITIVE_EVIDENCE -> restart facts",
        " 4 from facts     n=[0, 0, 0, 3, 3, 3, 3, 3] NO_POSITIVE_EVIDENCE -> restart facts",
        " 5 from facts     n=[0, 0, 0, 4, 4, 4, 4, 4] NO_POSITIVE_EVIDENCE -> restart facts",
        " 6 from facts     n=[0, 0, 0, 5, 5, 5, 5, 5] NO_POSITIVE_EVIDENCE -> restart timeline",
        " 7 from timeline  n=[0, 0, 1, 6, 6, 6, 6, 6] NO_POSITIVE_EVIDENCE -> restart facts",
        " 8 from facts     n=[0, 0, 1, 7, 7, 7, 7, 7] DEPTH_RANGE -> restart gating",
        " 9 from gating    n=[0, 0, 1, 7, 7, 8, 8, 8] DEPTH_RANGE -> restart gating",
        "10 from gating    n=[0, 0, 1, 7, 7, 9, 9, 9] ok",
    ]
    assert case.attempt == 10 and case.stage_attempts == (0, 0, 1, 7, 7, 9, 9, 9)


def test_the_skin_stage_draws_from_the_stream_of_its_counter():
    drawn = []

    def skin(ctx, stream, case):
        drawn.append(stream.below(2**32))
        return case

    run_pipeline(ctx_of(), validator=scripted([[FACTS_CODE]]), skin=skin)
    ctx = ctx_of()
    assert drawn == [ctx.stream("skin", n).below(2**32) for n in (0, 1)]


def test_the_twentieth_attempt_may_succeed_but_a_twenty_first_is_not_made():
    case, trace = run_pipeline(ctx_of(), validator=scripted([[FACTS_CODE]] * 19))
    assert case.attempt == 20 and len(trace.attempts) == 20
    with pytest.raises(CaseGenerationError, match="budget of 20 attempts ran out") as stopped:
        run_pipeline(ctx_of(), validator=scripted([[FACTS_CODE]] * 20))
    assert len(stopped.value.trace.attempts) == 20


def test_the_pipeline_follows_the_model_when_failures_pile_up():
    failures = [FACTS_CODE] * 7 + [GATING_CODE] * 2
    expected, _ = retry_model.model(["facts"] * 7 + ["gating"] * 2)
    validator = scripted([[c] for c in failures])
    _, trace = run_pipeline(ctx_of(), validator=validator, budget=50)
    assert [PIPELINE.index(a.restart) for a in trace.attempts[:-1]] == expected
    assert trace.attempts[-1].counters == retry_model.counters(expected)
    assert expected[5] == PIPELINE.index("timeline")  # the sixth facts failure escalated


# The run stops


def test_a_code_no_stage_can_fix_stops_the_run():
    pack = castle()
    with pytest.raises(CaseGenerationError, match="no stage can fix PACK_MISMATCH") as stopped:
        run_pipeline(ctx_of(), validator=scripted([[PLACEMENT_CODE, "PACK_MISMATCH"]]))
    error = stopped.value
    assert [a.restart for a in error.trace.attempts] == [None] and error.report is not None
    assert "PACK_MISMATCH" in error.report.codes() and pack.id == "castle"


def test_a_broken_reference_from_the_assembly_is_a_bug_not_a_retry():
    def skin(ctx, stream, case):
        return case.model_copy(update={"start": Start(facts=("nothing",))})

    with pytest.raises(CaseGenerationError, match="no stage can fix DANGLING_REF") as stopped:
        run_pipeline(ctx_of(), skin=skin)
    assert len(stopped.value.trace.attempts) == 1


def test_the_budget_of_attempts_ends_a_run_that_never_succeeds():
    validator = scripted([[FACTS_CODE]], then_real=False)
    with pytest.raises(CaseGenerationError, match="budget of 7 attempts ran out") as stopped:
        run_pipeline(ctx_of(), validator=validator, budget=7)
    attempts = stopped.value.trace.attempts
    assert len(attempts) == 7 and attempts[-1].restart is None and len(validator.calls) == 7


def test_a_run_that_used_up_every_stage_stops():
    validator = scripted([[ROSTER_CODE]], then_real=False)
    with pytest.raises(CaseGenerationError, match="every stage used up its retries") as stopped:
        run_pipeline(ctx_of(), validator=validator, budget=100)
    assert len(stopped.value.trace.attempts) == 6  # five restarts of roster, then no way back


def failing_once_at(stage: str, counter: int = 0, message: str = "no location with room"):
    def runner(ctx, at, out, n):
        if (at, n) == (stage, counter):
            raise GenerationError(message)
        return run_stage(ctx, at, out, n)

    return runner


def test_a_stage_that_raises_is_a_failed_attempt_restarted_with_a_new_stream():
    case, trace = run_pipeline(ctx_of(), runner=failing_once_at("placement"))
    one, two = trace.attempts
    assert (one.codes, one.detail, one.restart) == (
        ("STAGE_ERROR",),
        "no location with room",
        "placement",
    )
    assert one.first_stage == "roster" and one.counters == (0,) * 8
    assert (two.first_stage, two.counters, two.codes) == ("placement", (0, 0, 0, 0, 1, 1, 1, 1), ())
    assert trace.lines()[0].endswith("STAGE_ERROR (no location with room) -> restart placement")
    assert case.attempt == 2 and case.stage_attempts == (0, 0, 0, 0, 1, 1, 1, 1)


def test_a_stage_that_always_raises_ends_the_run_with_its_own_message():
    def runner(ctx, stage, out, counter):
        if stage == "placement":
            raise GenerationError("no location with room")
        return run_stage(ctx, stage, out, counter)

    with pytest.raises(CaseGenerationError, match="budget of 20 attempts ran out") as stopped:
        run_pipeline(ctx_of(), runner=runner)
    error = stopped.value
    assert "the placement stage failed: no location with room" in str(error)
    assert error.report is None and len(error.trace.attempts) == 20
    assert {a.codes for a in error.trace.attempts} == {("STAGE_ERROR",)}


def test_a_stage_output_that_makes_no_case_walks_back_to_the_stage_that_made_it():
    """The assembly cannot use a gating with a reference to nothing: it fails five times at
    `assemble`, then the controller restarts `gating`, whose new stream gives a clean output."""

    def runner(ctx, stage, out, counter):
        output = run_stage(ctx, stage, out, counter)
        if (stage, counter) == ("gating", 0):
            return output.model_copy(update={"start_facts": ("nope",)})
        return output

    case, trace = run_pipeline(ctx_of(), runner=runner)
    assert [a.restart for a in trace.attempts] == ["assemble"] * 5 + ["gating", None]
    assert "does not make a case" in trace.attempts[0].detail
    assert case.attempt == 7 and case.stage_attempts == (0, 0, 0, 0, 0, 1, 6, 6)


# Real faults, caught by the real validator


def test_a_facts_output_the_validator_rejects_is_redrawn():
    def runner(ctx, stage, out, counter):
        output = run_stage(ctx, stage, out, counter)
        if (stage, counter) != ("facts", 0):
            return output
        weak = tuple(
            f.model_copy(
                update={
                    "effects": tuple(e.model_copy(update={"kind": "supports"}) for e in f.effects)
                }
            )
            if f.id == "x_s0"
            else f
            for f in output.facts  # type: ignore[attr-defined]
        )
        return output.model_copy(update={"facts": weak})

    case, trace = run_pipeline(ctx_of(4, "standard"), runner=runner)
    first = trace.attempts[0]
    assert {"NO_POSITIVE_EVIDENCE", "SHAPE_MISMATCH"} <= set(first.codes)
    assert first.restart == "facts" and trace.attempts[-1].codes == ()
    assert validate(case, castle(), Profile.STRICT).issues == ()


def test_a_gating_that_opens_everything_is_caught_and_the_earliest_stage_is_redrawn():
    def runner(ctx, stage, out, counter):
        output = run_stage(ctx, stage, out, counter)
        if (stage, counter) != ("gating", 0):
            return output
        assert isinstance(output, GatingOut)
        everyone = tuple(s.pos for s in out["truth"].roster.suspects)
        return output.model_copy(
            update={"suspect_requires": (), "record_requires": (), "start_suspects": everyone}
        )

    case, trace = run_pipeline(ctx_of(1, "long"), runner=runner)
    first = trace.attempts[0]
    assert (
        first.restart == "placement"
    )  # ACTIONS_RANGE (placement) comes before DEPTH_RANGE (gating)
    assert {"ACTIONS_RANGE", "DEPTH_RANGE"} <= set(first.codes)
    assert case.stage_attempts == (0, 0, 0, 0, 1, 1, 1, 1)


# Replay and its refusals


def test_a_case_from_other_code_or_another_pack_is_refused():
    pack = castle()
    case = generate(2, "short", pack)

    def refuses(change, match, pack=pack):
        with pytest.raises(VersionMismatch, match=match):
            regenerate(case.model_copy(update=change), pack)

    refuses({"seed": None}, "not generated")
    refuses({"skeleton_algo_version": SKELETON_ALGO_VERSION + 1}, "skeleton algorithm")
    refuses({"generator_version": "roster=1"}, "was made by")
    refuses({"stage_attempts": (0, 0)}, "stage counters")
    other = castle().model_copy(update={"skeleton_rev": 9})
    with pytest.raises(VersionMismatch, match="another version of the pack"):
        regenerate(case, other)


@pytest.mark.parametrize(
    ("counters", "match"),
    [
        ({"nope": 1}, "bad stage counter"),
        ({"facts": -1}, "must not be negative"),
        ({"facts": True}, "bad stage counter"),
        ({"facts": 1.5}, "bad stage counter"),
    ],
)
def test_bad_stage_counters_are_refused(counters, match):
    with pytest.raises(ValueError, match=match):
        run_pipeline(ctx_of(), counters=counters)


def test_an_unhosted_preset_is_a_user_error_not_a_generation_failure():
    from gumshoe.cases.model.spec import UnsupportedPreset

    with pytest.raises(UnsupportedPreset):
        generate(1, "epic", castle())


def narrowed(depth_max: int = 3):
    """The presets with the `short` depth window widened: a different spec under the same name."""
    from gumshoe.cases.model.spec import PRESETS

    short = PRESETS["short"]
    limits = short.limits.model_copy(update={"depth_max": depth_max})
    return {**PRESETS, "short": short.model_copy(update={"limits": limits})}


def test_a_custom_preset_table_reaches_the_validator_too():
    pack, presets = castle(), narrowed()
    case, trace = generate_traced(1, "short", pack, presets)
    assert len(trace.attempts) == 1 and case.spec.limits.depth_max == 3
    assert skeleton_digest(regenerate(case, pack, presets)) == skeleton_digest(case)


def test_regenerate_will_not_draw_another_case_when_its_one_pass_fails(monkeypatch):
    from gumshoe.cases.generate import pipeline

    pack = castle()
    case = generate(2, "short", pack)
    monkeypatch.setattr(
        pipeline, "validate", lambda c, p, profile, presets: fake_report(c, [FACTS_CODE])
    )
    with pytest.raises(CaseGenerationError, match="budget of 1 attempt ran out"):
        regenerate(case, pack)


def test_a_case_retried_after_a_real_fault_is_exactly_regenerated():
    pack = castle()

    def runner(ctx, stage, out, counter):
        output = run_stage(ctx, stage, out, counter)
        if (stage, counter) != ("facts", 0):
            return output
        weak = tuple(
            f.model_copy(
                update={
                    "effects": tuple(e.model_copy(update={"kind": "supports"}) for e in f.effects)
                }
            )
            if f.id == "x_s0"
            else f
            for f in output.facts  # type: ignore[attr-defined]
        )
        return output.model_copy(update={"facts": weak})

    case, trace = run_pipeline(ctx_of(4, "standard"), runner=runner)
    assert len(trace.attempts) == 2 and case.stage_attempts == (0, 0, 0, 1, 1, 1, 1, 1)
    again = regenerate(case, pack)
    assert again.attempt == 1
    assert again.model_copy(update={"attempt": case.attempt}) == case


def test_regenerate_refuses_a_case_made_for_another_preset_table():
    pack = castle()
    case = generate(1, "short", pack, narrowed())
    with pytest.raises(VersionMismatch, match="another spec"):
        regenerate(case, pack)  # the default table gives another `short`


def test_the_case_id_names_the_spec_too():
    pack = castle()
    plain, widened = generate(1, "short", pack), generate(1, "short", pack, narrowed())
    assert plain.spec != widened.spec and plain.id != widened.id


def test_a_budget_of_no_attempt_is_refused():
    with pytest.raises(ValueError, match="at least one attempt"):
        run_pipeline(ctx_of(), budget=0)


def test_a_stage_error_without_a_message_still_shows_in_the_trace():
    case, trace = run_pipeline(ctx_of(), runner=failing_once_at("placement", message=""))
    assert trace.attempts[0].detail == "GenerationError" and case.attempt == 2


# The text lint is part of the same attempt as the validator


def failing_lint(times: int):
    """A text lint that reports one problem on its first `times` calls and then finds nothing."""
    calls: list[int] = []

    def lint(case, pack):
        calls.append(1)
        return (
            (make("BAD_RENDER", "intro", problem="a stray brace"),) if len(calls) <= times else ()
        )

    lint.calls = calls  # type: ignore[attr-defined]
    return lint


def test_a_lint_failure_redraws_the_skin_and_nothing_before_it():
    log: list[tuple[str, int]] = []
    lint = failing_lint(2)
    case, trace = run_pipeline(ctx_of(), runner=recording(log), lint=lint)
    assert log == [(stage, 0) for stage in PIPELINE[:6]]  # the structure ran once
    assert [(a.codes, a.restart) for a in trace.attempts] == [
        (("BAD_RENDER",), "skin"),
        (("BAD_RENDER",), "skin"),
        ((), None),
    ]
    assert trace.attempts[0].detail.startswith("intro: ") and len(lint.calls) == 3
    assert case.stage_attempts == (0, 0, 0, 0, 0, 0, 0, 2) and case.attempt == 3


def test_a_clean_case_costs_one_attempt_for_the_validator_and_the_lint_together():
    lint = failing_lint(0)
    case, trace = run_pipeline(ctx_of(), lint=lint)
    assert case.attempt == 1 and len(trace.attempts) == 1 and len(lint.calls) == 1


def test_the_lint_is_not_asked_about_a_case_the_validator_rejects():
    lint = failing_lint(0)
    run_pipeline(ctx_of(), validator=scripted([[FACTS_CODE]]), lint=lint)
    assert len(lint.calls) == 1  # only the second attempt got as far as the lint


def test_a_lint_that_never_passes_ends_with_the_budget_and_the_problem():
    with pytest.raises(CaseGenerationError, match="budget of 20 attempts ran out") as stopped:
        run_pipeline(ctx_of(), lint=failing_lint(99))
    error = stopped.value
    assert "intro: the rendered text has a stray brace" in str(error) and error.report is None
    assert len(error.trace.attempts) == 20


def test_five_lint_failures_in_a_row_make_the_controller_step_back_to_assemble():
    _, trace = run_pipeline(ctx_of(), lint=failing_lint(6))
    assert [a.restart for a in trace.attempts] == ["skin"] * 5 + ["assemble", None]


def test_a_lint_that_cannot_check_a_text_fails_the_skin_stage_not_the_run():
    def lint(case, pack):
        raise GenerationError("the lint found no place")

    with pytest.raises(CaseGenerationError, match="the skin stage failed: the lint found no") as e:
        run_pipeline(ctx_of(), lint=lint, budget=3)
    assert [a.codes for a in e.value.trace.attempts] == [("STAGE_ERROR",)] * 3


def test_a_skin_that_raises_on_a_sound_skeleton_is_a_skin_stage_error():
    def skin(ctx, stream, case):
        raise GenerationError("no text for hints/fear")

    with pytest.raises(CaseGenerationError, match="the skin stage failed: no text for hints"):
        run_pipeline(ctx_of(), skin=skin, budget=3)
