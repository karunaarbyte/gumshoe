from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact, replace_in


def graph_of(case):
    return build_graph(CaseIndex.of(case))


def test_fixture_graph_is_acyclic_with_the_cellar_gate_as_an_ancestor():
    g = graph_of(build_case())
    assert g.cycle == () and len(g.order) == 22
    assert g.anc["f_clara_keys"] == frozenset({"f_key"})  # the cellar needs the key
    assert g.anc["f_key"] == frozenset() and g.anc["f_proof_boris"] == frozenset()
    assert g.depth["f_key"] == 0 and g.depth["f_clara_keys"] == 1


def test_ancestors_are_transitive_and_depth_is_the_longest_chain():
    case = replace_fact(
        replace_fact(build_case(), "f_alibi_anna", requires=("f_key",)),
        "f_absent_rope",
        requires=("f_alibi_anna",),
    )
    g = graph_of(case)
    assert g.anc["f_absent_rope"] == frozenset({"f_alibi_anna", "f_key"})
    assert g.depth["f_absent_rope"] == 2


def test_cycles_are_detected_and_include_facts_behind_them():
    case = replace_fact(
        replace_fact(build_case(), "f_key", requires=("f_alibi_anna",)),
        "f_alibi_anna",
        requires=("f_key",),
    )
    g = graph_of(case)
    assert {"f_key", "f_alibi_anna"} <= set(g.cycle)
    assert "f_clara_keys" in g.cycle  # gated behind the cellar, which needs the key
    assert "f_proof_boris" not in g.cycle


def test_a_fact_gated_by_its_own_location_is_a_self_cycle():
    case = replace_in(build_case(), "locations", "l_cellar", requires=("f_clara_keys",))
    assert "f_clara_keys" in graph_of(case).cycle


def test_a_fact_requiring_itself_is_a_cycle():
    case = replace_fact(build_case(), "f_absent_rope", requires=("f_absent_rope",))
    assert graph_of(case).cycle == ("f_absent_rope",)


def test_dangling_prerequisites_are_ignored_by_the_graph():
    assert graph_of(replace_fact(build_case(), "f_key", requires=("f_nope",))).cycle == ()


def test_group_3_reports_one_issue_listing_the_cyclic_facts_and_skips_dependent_groups():
    case = replace_fact(
        replace_fact(build_case(), "f_key", requires=("f_alibi_anna",)),
        "f_alibi_anna",
        requires=("f_key",),
    )
    report = validate(case, profile=Profile.CUSTOM)
    (issue,) = report.of_code("DEPENDENCY_CYCLE")
    assert {"f_key", "f_alibi_anna"} <= set(issue.subjects)
    assert set(report.skipped_groups) >= {4, 5, 6, 8, 9, 10}
