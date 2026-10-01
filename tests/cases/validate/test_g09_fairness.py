from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.groups.g09_fairness import owner
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.mutations import MUTATIONS

ix = CaseIndex.of(build_case())


def g09(case, profile=Profile.CUSTOM):
    return [i for i in validate(case, profile=profile).issues if i.group == 9]


def test_ownership_prefers_the_who_effect_then_the_record_subject_then_the_speaker():
    assert owner(ix, ix.facts["f_sup_boris"]) == "s_boris"  # who effect beats the speaker (Anna)
    assert owner(ix, ix.facts["f_secret_anna"]) == "s_anna"  # a record about Anna
    assert owner(ix, ix.facts["f_lie_anna"]) == "s_anna"
    assert owner(ix, ix.facts["f_trace_poison"]) is None  # a how-axis search fact has no owner
    assert owner(ix, ix.facts["f_sup_poison"]) is None  # a record about a location, no who effect


def test_the_fixture_gives_every_suspect_four_facts_one_lie_and_one_exposure():
    assert g09(build_case()) == []


def test_uneven_counts_name_every_suspect_and_the_spread():
    case = MUTATIONS["FACTS_UNEVEN"].apply(build_case())
    (issue,) = [i for i in g09(case) if i.code == "FACTS_UNEVEN"]
    assert (
        issue.subjects == ("s_anna", "s_boris", "s_clara") and dict(issue.params)["spread"] == "2"
    )


def test_a_spread_within_the_tolerance_is_not_uneven():
    case = MUTATIONS["CULPRIT_UNIQUE_EXTREME"].apply(build_case())
    assert "FACTS_UNEVEN" not in {i.code for i in g09(case)}


def test_the_culprit_as_the_unique_maximum_is_flagged_as_a_spoiler_with_the_feature():
    case = MUTATIONS["CULPRIT_UNIQUE_EXTREME"].apply(build_case())
    (issue,) = [i for i in g09(case) if i.code == "CULPRIT_UNIQUE_EXTREME"]
    assert (
        issue.subjects == ("s_boris",)
        and dict(issue.params)["feature"] == "FACTS_UNEVEN"
        and issue.spoiler
    )


def test_a_tie_for_the_extreme_is_not_unique():
    case = MUTATIONS["FACTS_UNEVEN"].apply(
        build_case()
    )  # Anna has 6, Boris and Clara 4: the culprit ties
    assert "CULPRIT_UNIQUE_EXTREME" not in {i.code for i in g09(case)}


def test_shape_mismatch_names_the_axis():
    (issue,) = g09(MUTATIONS["SHAPE_MISMATCH"].apply(build_case()))
    assert issue.code == "SHAPE_MISMATCH" and issue.axis.value == "who"


def test_truth_depth_extreme_only_when_the_truth_is_strictly_deeper_or_shallower_than_all_others():
    (issue,) = g09(MUTATIONS["TRUTH_DEPTH_EXTREME"].apply(build_case()))
    assert (
        issue.code == "TRUTH_DEPTH_EXTREME"
        and issue.subjects == ("m_poison",)
        and issue.axis.value == "how"
    )


def test_group_9_issues_are_warnings_when_imported_and_errors_when_strict():
    case = MUTATIONS["SHAPE_MISMATCH"].apply(build_case())
    assert g09(case, Profile.STRICT)[0].severity.value == "error"
    assert g09(case, Profile.IMPORTED)[0].severity.value == "warning"
    assert validate(case, profile=Profile.IMPORTED).ok
