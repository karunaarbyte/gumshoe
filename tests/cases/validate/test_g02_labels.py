from gumshoe.cases.model.enums import Axis
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_in


def report_for(case, profile=Profile.CUSTOM):
    return validate(case, profile=profile)


def test_fixture_labels_are_clean():
    assert not any(i.group == 2 for i in report_for(build_case()).issues)


def test_overlap_names_both_candidates_and_the_axis():
    case = replace_in(build_case(), "methods", "m_rope", label="poison")
    (issue,) = report_for(case).of_code("LABEL_OVERLAP")
    assert (
        set(issue.subjects) == {"m_poison", "m_rope"}
        and issue.axis is Axis.HOW
        and dict(issue.params)["kind"] == "subset"
    )


def test_stemming_catches_inflected_overlaps():
    case = replace_in(build_case(), "methods", "m_rope", label="poisoning")  # stems to "poison"
    assert "LABEL_OVERLAP" in report_for(case).codes()


def test_the_same_label_on_different_axes_is_a_duplicate():
    case = replace_in(
        build_case(), "motives", "v_jealousy", label="strangled with a rope", aliases=("envy",)
    )
    assert "LABEL_DUPLICATE" in report_for(case).codes()


def test_alias_collisions_are_pairwise_and_reported_once():
    case = replace_in(build_case(), "methods", "m_dagger", aliases=("knife", "rope"))
    issues = report_for(case).of_code("ALIAS_COLLISION")
    assert len(issues) == 1 and set(issues[0].subjects) == {"m_dagger", "m_rope"}


def test_a_suspect_name_inside_a_motive_label_is_flagged_with_the_tokens():
    case = replace_in(build_case(), "motives", "v_debt", label="to cover a debt owed to Boris")
    (issue,) = report_for(case).of_code("LABEL_NAME_COLLISION")
    assert issue.subjects == ("v_debt",) and dict(issue.params)["tokens"] == "bori"


def test_length_skew_is_an_error_when_strict_and_a_warning_when_imported():
    case = replace_in(
        replace_in(build_case(), "motives", "v_jealousy", label="jealousy"),
        "motives",
        "v_debt",
        label="to cover a truly enormous and ruinous gambling debt incurred over many long years",
    )
    strict = report_for(case, Profile.STRICT)
    imported = report_for(case, Profile.IMPORTED)
    assert strict.of_code("LABEL_LENGTH_SKEW")[0].severity.value == "error"
    assert imported.of_code("LABEL_LENGTH_SKEW")[0].severity.value == "warning"


def test_every_candidate_needs_a_distinctive_token():
    case = replace_in(build_case(), "methods", "m_poison", label="dagger rope", aliases=())
    (issue,) = report_for(case).of_code("NO_DISTINCTIVE_TOKEN")
    assert issue.subjects == ("m_poison",)


def test_blank_labels_do_not_crash_and_are_not_duplicates_of_each_other():
    case = replace_in(
        replace_in(build_case(), "methods", "m_rope", label=""), "methods", "m_dagger", label=""
    )
    assert "LABEL_DUPLICATE" not in report_for(case).codes()


def test_a_blank_label_has_no_distinctive_token():
    case = replace_in(build_case(), "methods", "m_rope", label="", aliases=())
    assert "NO_DISTINCTIVE_TOKEN" in report_for(case).codes()


def test_distinctiveness_is_judged_within_the_axis():
    # a motive sharing the word "wine" with a method must not lose its distinctive token
    case = replace_in(build_case(), "motives", "v_debt", label="wine", aliases=())
    assert "NO_DISTINCTIVE_TOKEN" not in report_for(case).codes()
