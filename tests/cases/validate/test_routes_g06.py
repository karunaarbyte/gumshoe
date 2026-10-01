from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.routes import axis_routes
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import drop_fact, replace_fact

WHO, HOW, WHY = Axis.WHO, Axis.HOW, Axis.WHY


def routes_for(case, axis):
    ix = CaseIndex.of(case)
    return axis_routes(ix, build_graph(ix), compute_reach(ix).facts, axis)


def shapes(case, axis):
    return {(r.kind, tuple(sorted(r.facts))) for r in routes_for(case, axis)}


def test_fixture_has_a_proves_route_and_an_elimination_route_per_axis():
    case = build_case()
    assert shapes(case, WHO) == {
        ("proves", ("f_proof_boris",)),
        ("elimination", ("f_alibi_anna", "f_clara_keys", "f_key")),
    }
    assert shapes(case, HOW) == {
        ("proves", ("f_trace_poison",)),
        ("elimination", ("f_absent_dagger", "f_absent_rope")),
    }
    assert shapes(case, WHY) == {
        ("proves", ("f_secret_boris",)),
        ("elimination", ("f_ruleout_inheritance", "f_ruleout_jealousy")),
    }


def test_routes_include_ancestors_through_gates():
    assert ("elimination", ("f_alibi_anna", "f_clara_keys", "f_key")) in shapes(
        build_case(), WHO
    )  # the cellar's key


def test_routes_use_only_truthful_facts():
    case = replace_fact(
        build_case(), "f_lie_boris", effects=()
    )  # lies carry rule-outs: irrelevant to routes
    assert {r.kind for r in routes_for(case, WHO)} == {"proves", "elimination"}


def test_an_unreachable_proves_fact_is_not_a_route():
    case = drop_fact(build_case(), "f_proof_boris")
    assert {r.kind for r in routes_for(case, WHO)} == {"elimination"}


def test_elimination_needs_a_rule_out_for_every_wrong_candidate():
    case = replace_fact(build_case(), "f_absent_dagger", effects=())
    assert {r.kind for r in routes_for(case, HOW)} == {"proves"}


def test_the_cheapest_rule_out_is_chosen_per_candidate_with_ties_broken_by_id():
    from gumshoe.cases.model.entities import Effect
    from gumshoe.cases.model.enums import EffectKind

    extra = replace_fact(
        build_case(),
        "f_sup_dagger",
        effects=(Effect(axis=HOW, candidate="m_dagger", kind=EffectKind.RULES_OUT),),
    )
    chosen = {r.kind: r.facts for r in routes_for(extra, HOW)}["elimination"]
    assert chosen == frozenset(
        {"f_absent_dagger", "f_absent_rope"}
    )  # both cost 0; the lower id wins


def g06(case):
    return [i for i in validate(case, profile=Profile.CUSTOM).issues if i.group == 6]


def test_fixture_is_solvable_on_every_axis():
    assert g06(build_case()) == []


def test_truth_ruled_out_names_the_ruling_facts_and_axis():
    from tests.cases.mutations import MUTATIONS

    (issue,) = [
        i
        for i in g06(MUTATIONS["TRUTH_RULED_OUT"].apply(build_case()))
        if i.code == "TRUTH_RULED_OUT"
    ]
    assert issue.subjects == ("f_sup_boris",) and issue.axis is WHO and issue.spoiler


def test_wrong_survivor_names_the_candidate():
    from tests.cases.mutations import MUTATIONS

    (issue,) = [
        i
        for i in g06(MUTATIONS["WRONG_SURVIVES"].apply(build_case()))
        if i.code == "WRONG_SURVIVES"
    ]
    assert issue.subjects == ("m_dagger",) and issue.axis is HOW


def _supports_poison(case, fact_id, **changes):
    from gumshoe.cases.model.entities import Effect
    from gumshoe.cases.model.enums import EffectKind

    effects = (Effect(axis=HOW, candidate="m_poison", kind=EffectKind.SUPPORTS),)
    return replace_fact(case, fact_id, effects=effects, **changes)


def test_supports_from_a_single_source_are_not_enough_positive_evidence():
    case = replace_fact(build_case(), "f_trace_poison", effects=())
    case = _supports_poison(case, "f_sup_dagger")  # gate_log/l_garden twice: still one source
    assert "NO_POSITIVE_EVIDENCE" in {i.code for i in g06(case)}


def test_supports_from_two_distinct_sources_count_as_positive_evidence():
    from tests.cases.fixtures import search

    case = replace_fact(build_case(), "f_trace_poison", effects=())
    case = _supports_poison(case, "f_sup_dagger", source=search("l_garden"))
    assert "NO_POSITIVE_EVIDENCE" not in {i.code for i in g06(case)}


def test_a_route_that_fails_the_shared_gate_is_no_route(monkeypatch):
    from gumshoe.cases.model.types import Held  # noqa: F401
    from gumshoe.cases.rules import gate

    monkeypatch.setattr(
        gate, "permission", lambda *a, **k: gate.Permission(allowed=False, warn=False)
    )
    (issue, *_) = [i for i in g06(build_case()) if i.code == "NO_ROUTE"]
    assert dict(issue.params)["reason"] == "gate"
