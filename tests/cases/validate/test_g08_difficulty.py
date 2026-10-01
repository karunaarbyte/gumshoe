from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.routes import best_solution
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact
from tests.cases.mutations import MUTATIONS


def solution(case):
    ix = CaseIndex.of(case)
    return best_solution(ix, build_graph(ix), compute_reach(ix).facts)


def g08(case, profile=Profile.CUSTOM):
    return [i for i in validate(case, profile=profile).issues if i.group == 8]


def test_the_fixtures_cheapest_solution_is_the_three_proves_facts():
    s = solution(build_case())
    assert s is not None and s.facts == frozenset(
        {"f_proof_boris", "f_trace_poison", "f_secret_boris"}
    )
    assert (s.size, s.depth, s.actions) == (
        3,
        0,
        2,
    )  # sources: search(l_study) and record(ledger, s_boris)


def test_a_shared_gate_on_both_how_routes_raises_depth_size_and_actions():
    s = solution(
        MUTATIONS["SINGLE_POINT_OF_FAILURE"].apply(build_case())
    )  # both how routes need the key
    assert s is not None and s.size == 4 and s.depth == 1 and s.actions == 3


def test_no_solution_when_an_axis_has_no_route():
    case = replace_fact(
        replace_fact(build_case(), "f_trace_poison", effects=()), "f_absent_dagger", effects=()
    )
    assert solution(case) is None


def test_ties_are_broken_deterministically():
    assert solution(build_case()) == solution(build_case())


def test_fixture_has_no_group_8_issues():
    assert g08(build_case()) == []


def test_limit_violations_report_size_min_and_max():
    (issue,) = [
        i
        for i in g08(MUTATIONS["SOLUTION_SIZE_RANGE"].apply(build_case()))
        if i.code == "SOLUTION_SIZE_RANGE"
    ]
    assert dict(issue.params) == {"max": "12", "min": "5", "size": "3"}


def test_decisive_ratio_counts_truthful_proves_facts_only():
    (issue,) = [
        i
        for i in g08(MUTATIONS["DECISIVE_RATIO"].apply(build_case()))
        if i.code == "DECISIVE_RATIO"
    ]
    assert dict(issue.params) == {"decisive": "3", "total": "22"}


def test_single_point_of_failure_names_the_fact_and_axis_and_is_a_spoiler():
    (issue,) = g08(MUTATIONS["SINGLE_POINT_OF_FAILURE"].apply(build_case()))
    assert (
        issue.code == "SINGLE_POINT_OF_FAILURE"
        and issue.subjects == ("f_key",)
        and issue.axis.value == "how"
        and issue.spoiler
    )


def test_single_point_of_failure_is_only_a_warning_when_imported():
    case = MUTATIONS["SINGLE_POINT_OF_FAILURE"].apply(build_case())
    (issue,) = g08(case, Profile.IMPORTED)
    assert issue.severity.value == "warning"


def test_start_facts_are_not_removable_so_they_are_not_tested():
    from tests.cases.helpers import replace_start

    case = replace_start(MUTATIONS["SINGLE_POINT_OF_FAILURE"].apply(build_case()), facts=("f_key",))
    assert not any(i.code == "SINGLE_POINT_OF_FAILURE" for i in g08(case))


def test_best_solution_stays_cheap_with_many_proves_facts_per_axis():
    import time

    from gumshoe.cases.model.entities import Effect, Fact
    from gumshoe.cases.model.enums import Axis, EffectKind, FactKind
    from tests.cases.fixtures import search

    effects = (
        Effect(axis=Axis.WHO, candidate="s_boris", kind=EffectKind.PROVES),
        Effect(axis=Axis.HOW, candidate="m_poison", kind=EffectKind.PROVES),
        Effect(axis=Axis.WHY, candidate="v_debt", kind=EffectKind.PROVES),
    )
    many = tuple(
        Fact(id=f"f_p{i}", kind=FactKind.CLUE, source=search("l_study"), effects=effects)
        for i in range(120)
    )
    case = build_case().model_copy(update={"facts": (*build_case().facts, *many)})
    started = time.perf_counter()
    assert solution(case) is not None
    assert time.perf_counter() - started < 2.0
