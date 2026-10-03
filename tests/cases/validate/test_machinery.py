import pytest

from gumshoe.cases.core.enums import FixStage
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.validate import runner
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Hint, HintOp, Issue, Profile, Report, Severity
from gumshoe.cases.validate.runner import REQUIRES, validate
from tests.cases.fixtures import build_case

E, W, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO


def test_catalogue_is_complete_and_consistent():
    assert len(CATALOGUE) == 81
    assert all(spec.code == code for code, spec in CATALOGUE.items())
    assert {spec.group for spec in CATALOGUE.values()} == set(range(0, 12))
    assert all(
        isinstance(spec.fix_stage, FixStage) and isinstance(spec.hint, HintOp)
        for spec in CATALOGUE.values()
    )
    assert all(spec.message for spec in CATALOGUE.values())


def test_group_9_is_a_warning_when_imported_and_an_error_when_strict():
    group9 = [s for s in CATALOGUE.values() if s.group == 9]
    assert {s.code for s in group9} == {
        "FACTS_UNEVEN",
        "LIES_UNEVEN",
        "EXPOSURES_UNEVEN",
        "CULPRIT_UNIQUE_EXTREME",
        "SHAPE_MISMATCH",
        "TRUTH_DEPTH_EXTREME",
    }
    assert all(s.severity_strict is E and s.severity_imported is W for s in group9)


def test_other_profile_specific_severities():
    assert CATALOGUE["LABEL_LENGTH_SKEW"].severity_imported is W
    assert (
        CATALOGUE["SINGLE_POINT_OF_FAILURE"].severity_strict is E
        and CATALOGUE["SINGLE_POINT_OF_FAILURE"].severity_imported is W
    )
    assert (
        CATALOGUE["PACK_RULES_SKIPPED"].severity_strict is E
        and CATALOGUE["PACK_RULES_SKIPPED"].severity_imported is INFO
    )
    assert CATALOGUE["DUPLICATE_ID"].severity_imported is E


def test_pack_bound_codes_are_flagged():
    pack_bound = {c for c, s in CATALOGUE.items() if s.requires_pack}
    assert pack_bound == {
        "PACK_MISMATCH",
        "SPEC_MISMATCH",
        "PACK_CAPACITY",
        "PACK_SOURCE_KIND_CAPACITY",
        "SCENE_NOT_IN_PACK",
        "SCENE_METHOD_NOT_ALLOWED",
        "ROLE_UNKNOWN",
        "ROLE_MOTIVE_NOT_ALLOWED",
        "ROLE_RECORD_KIND_NOT_ALLOWED",
        "LOCATION_KIND_NOT_IN_PACK",
        "LOCATION_KIND_NOT_IN_SCENE",
        "TRACE_KIND_NOT_ALLOWED",
        "TRACE_KIND_MISSING",
        "RECORD_KIND_NOT_IN_PACK",
        "CLAIM_SUBJECT_MISMATCH",
        "RECORD_SUBJECT_MISMATCH",
    }


def test_spoiler_flags_mark_codes_that_name_the_truth():
    spoilers = {c for c, s in CATALOGUE.items() if s.spoiler}
    assert {
        "TRUTH_RULED_OUT",
        "WRONG_SURVIVES",
        "NO_ROUTE",
        "CULPRIT_NO_OPPORTUNITY",
        "SINGLE_POINT_OF_FAILURE",
    } <= spoilers
    assert "DUPLICATE_ID" not in spoilers


def test_ctx_builds_issues_from_the_catalogue_by_profile():
    ctx = Ctx(case=build_case(), pack=None, profile=Profile.STRICT)
    issue = ctx.issue("FACTS_UNEVEN", "s_anna", "s_boris", axis=Axis.WHO, spread=3)
    assert issue.severity is E and issue.group == 9 and issue.subjects == ("s_anna", "s_boris")
    assert issue.axis is Axis.WHO and issue.params == (("spread", "3"),)
    assert (
        issue.hint.op is CATALOGUE["FACTS_UNEVEN"].hint
        and issue.fix_stage is CATALOGUE["FACTS_UNEVEN"].fix_stage
    )
    assert (
        Ctx(case=build_case(), pack=None, profile=Profile.IMPORTED).issue("FACTS_UNEVEN").severity
        is W
    )
    assert (
        Ctx(case=build_case(), pack=None, profile=Profile.CUSTOM).issue("FACTS_UNEVEN").severity
        is E
    )  # custom = strict


def test_ctx_rejects_unknown_codes():
    with pytest.raises(KeyError):
        Ctx(case=build_case(), pack=None, profile=Profile.STRICT).issue("NOT_A_CODE")


def make_issue(code="DUPLICATE_ID", subjects=("a",), axis=None, params=()):
    spec = CATALOGUE[code]
    return Issue(
        code=code,
        severity=spec.severity_strict,
        group=spec.group,
        subjects=subjects,
        axis=axis,
        params=params,
        hint=Hint(spec.hint),
        spoiler=spec.spoiler,
        fix_stage=spec.fix_stage,
    )


def test_report_properties_and_canonical_bytes_are_deterministic():
    one, two = make_issue("DUPLICATE_ID"), make_issue("LABEL_OVERLAP", ("x", "y"))
    a = Report(profile=Profile.STRICT, issues=(one, two))
    b = Report(profile=Profile.STRICT, issues=(one, two))
    assert a.canonical() == b.canonical() and a.codes() == {"DUPLICATE_ID", "LABEL_OVERLAP"}
    assert not a.ok and Report(profile=Profile.STRICT, issues=()).ok
    only_warning = Issue(**{**one.__dict__, "severity": W})
    assert Report(profile=Profile.STRICT, issues=(only_warning,)).ok
    assert a.of_code("LABEL_OVERLAP") == (two,)


def test_runner_sorts_issues_and_skips_groups_whose_prerequisites_failed(monkeypatch):
    calls: list[int] = []

    def fake(group: int, *codes: str):
        def run(ctx: Ctx) -> list[Issue]:
            calls.append(group)
            return [ctx.issue(code, "x") for code in codes]

        return run

    monkeypatch.setattr(
        runner,
        "RUNNERS",
        {
            1: fake(1),
            2: fake(2, "LABEL_OVERLAP"),
            3: fake(3, "DEPENDENCY_CYCLE"),
            4: fake(4),
            5: fake(5),
            6: fake(6),
            7: fake(7, "DOUBLE_BOOKED"),
            8: fake(8),
            9: fake(9),
            10: fake(10),
            11: fake(11),
        },
    )
    report = validate(build_case(), profile=Profile.CUSTOM)
    # group 3 failed: 4, 5, 6, 8, 9 and 10 are skipped (skipping propagates); 2, 7 and 11 still run
    assert calls == [1, 2, 3, 7, 11]
    assert report.skipped_groups == (4, 5, 6, 8, 9, 10)
    assert [i.code for i in report.issues] == [
        "LABEL_OVERLAP",
        "DEPENDENCY_CYCLE",
        "DOUBLE_BOOKED",
    ]  # sorted by group


def test_group_1_failure_skips_everything_else(monkeypatch):
    monkeypatch.setattr(
        runner,
        "RUNNERS",
        {
            g: (lambda ctx, g=g: [ctx.issue("DUPLICATE_ID", "x")] if g == 1 else [])
            for g in range(1, 12)
        },
    )
    report = validate(build_case(), profile=Profile.CUSTOM)
    assert report.skipped_groups == tuple(range(2, 12))


def test_warnings_do_not_block_later_groups(monkeypatch):
    monkeypatch.setattr(
        runner,
        "RUNNERS",
        {
            g: (lambda ctx, g=g: [ctx.issue("LABEL_LENGTH_SKEW", "x")] if g == 2 else [])
            for g in range(1, 12)
        },
    )
    report = validate(build_case(), profile=Profile.IMPORTED)
    assert report.skipped_groups == ()


def test_internal_error_is_group_zero_and_never_a_runner_key():
    spec = CATALOGUE["INTERNAL_ERROR"]
    assert spec.group == 0 and spec.severity_strict is E and spec.severity_imported is E
    assert 0 not in runner.RUNNERS and 0 not in REQUIRES


def test_a_crashing_group_becomes_an_internal_error_and_blocks_its_dependants(monkeypatch):
    def boom(ctx: Ctx) -> list[Issue]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(runner, "RUNNERS", {1: lambda ctx: [], 3: boom, 4: lambda ctx: []})
    report = validate(build_case(), profile=Profile.CUSTOM)
    (issue,) = report.of_code("INTERNAL_ERROR")
    assert (
        issue.group == 0
        and issue.subjects == ("3",)
        and report.skipped_groups == (4, 5, 6, 8, 9, 10)
    )


def test_blocked_groups_are_reported_skipped_even_when_unregistered(monkeypatch):
    monkeypatch.setattr(runner, "RUNNERS", {1: lambda ctx: [ctx.issue("DUPLICATE_ID", "x")]})
    assert validate(build_case(), profile=Profile.CUSTOM).skipped_groups == tuple(range(2, 12))


def test_prerequisite_table():
    assert REQUIRES[1] == frozenset() and REQUIRES[10] == frozenset({1, 3})
    assert (
        REQUIRES[4] == frozenset({1, 3})
        and REQUIRES[6] == frozenset({1, 3, 4})
        and REQUIRES[8] == frozenset({1, 3, 4, 6})
    )
    assert all(1 in REQUIRES[g] for g in range(2, 12))
