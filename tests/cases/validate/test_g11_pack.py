from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import TINY_PRESETS, build_pack, build_strict_case
from tests.cases.mutations import MUTATIONS, run_mutation


def strict(case=None, pack=None, profile=Profile.STRICT):
    return validate(
        case or build_strict_case(),
        pack if pack is not None else build_pack(),
        profile,
        TINY_PRESETS,
    )


def test_the_strict_fixture_with_its_pack_is_completely_clean():
    report = strict()
    assert report.issues == () and report.skipped_groups == ()


def test_a_generated_case_without_a_pack_is_never_silently_clean_under_strict():
    report = validate(build_strict_case(), None, Profile.STRICT, TINY_PRESETS)
    (issue,) = report.of_code("PACK_RULES_SKIPPED")
    assert issue.severity.value == "error" and not report.ok
    assert set(dict(issue.params)["skipped"].split(",")) == {
        "PACK_MISMATCH",
        "SPEC_MISMATCH",
        "PACK_CAPACITY",
        "PACK_SOURCE_KIND_CAPACITY",
        "SCENE_NOT_IN_PACK",
        "SCENE_METHOD_NOT_ALLOWED",
        "ROLE_UNKNOWN",
        "ROLE_MOTIVE_NOT_ALLOWED",
        "ROLE_RECORD_KIND_NOT_ALLOWED",
    }


def test_the_skip_notice_is_only_informational_when_imported_and_absent_for_custom():
    case = build_strict_case()
    imported = validate(case, None, Profile.IMPORTED, TINY_PRESETS)
    assert imported.of_code("PACK_RULES_SKIPPED")[0].severity.value == "info" and imported.ok
    assert validate(case, None, Profile.CUSTOM, TINY_PRESETS).issues == ()


def test_custom_profile_skips_pack_rules_silently_even_when_a_pack_is_supplied():
    case = MUTATIONS["PACK_MISMATCH"].apply(build_strict_case())
    assert not [
        i
        for i in validate(case, build_pack(), Profile.CUSTOM, TINY_PRESETS).issues
        if i.group == 11
    ]


def test_imported_cases_skip_spec_and_pack_reference_checks_but_keep_plausibility():
    from gumshoe.cases.model.enums import Origin

    case = (
        MUTATIONS["PACK_MISMATCH"]
        .apply(build_strict_case())
        .model_copy(update={"origin": Origin.IMPORTED})
    )
    codes = validate(case, build_pack(), Profile.IMPORTED, TINY_PRESETS).codes()
    assert "PACK_MISMATCH" not in codes and "SPEC_MISMATCH" not in codes


def test_an_unsupported_or_unknown_preset_is_a_spec_mismatch_with_a_reason():
    from tests.cases.helpers import replace_spec

    case = replace_spec(build_strict_case(), preset="epic")
    (issue,) = validate(case, build_pack(), Profile.STRICT, TINY_PRESETS).of_code("SPEC_MISMATCH")
    assert "unknown" in dict(issue.params)["reason"]


def test_capacity_issue_names_what_exceeds_what():
    report = run_mutation(MUTATIONS["PACK_CAPACITY"])
    (issue,) = report.of_code("PACK_CAPACITY")
    assert issue.subjects == ("suspects",) and dict(issue.params) == {"actual": "3", "max": "2"}


def test_the_per_kind_check_uses_integer_arithmetic_at_the_boundary():
    report = run_mutation(MUTATIONS["PACK_SOURCE_KIND_CAPACITY"])
    (issue,) = report.of_code("PACK_SOURCE_KIND_CAPACITY")
    assert issue.subjects == ("search",) and dict(issue.params)["demand"] == "10"
    # 9 search facts would be exactly allowed (45 <= 48); the fixture's 7 are well within
    assert not validate(build_strict_case(), build_pack(), Profile.STRICT, TINY_PRESETS).of_code(
        "PACK_SOURCE_KIND_CAPACITY"
    )
