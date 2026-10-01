from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.lies import valid_exposers
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact


def g05(case):
    return [i for i in validate(case, profile=Profile.CUSTOM).issues if i.group == 5]


def exposers(case, lie_id):
    ix = CaseIndex.of(case)
    return [
        f.id for f in valid_exposers(ix, build_graph(ix), compute_reach(ix).facts, ix.facts[lie_id])
    ]


def test_fixture_lies_each_have_exactly_one_valid_exposer():
    case = build_case()
    assert g05(case) == []
    assert exposers(case, "f_lie_boris") == ["f_secret_boris"]
    assert exposers(case, "f_lie_anna") == ["f_secret_anna"] and exposers(case, "f_lie_clara") == [
        "f_secret_clara"
    ]


def test_a_lie_listed_as_exposer_is_flagged_even_beside_a_valid_one():
    case = replace_fact(build_case(), "f_lie_anna", exposed_by=("f_secret_anna", "f_lie_boris"))
    assert [i.code for i in g05(case)] == ["EXPOSER_IS_LIE"]


def test_a_lie_with_no_valid_exposer_gets_one_specific_reason_per_bad_exposer():
    case = replace_fact(build_case(), "f_lie_anna", exposed_by=("f_lie_boris", "f_sup_boris"))
    codes = sorted(i.code for i in g05(case))
    assert codes == ["EXPOSER_IS_LIE", "EXPOSER_OWNED_BY_SPEAKER"]


def test_a_lie_that_is_its_own_exposer_is_caught():
    case = replace_fact(build_case(), "f_lie_anna", exposed_by=("f_lie_anna",))
    assert "EXPOSER_IS_LIE" in {i.code for i in g05(case)}


def test_hook_must_name_a_valid_exposers_source():
    ok = build_case()
    assert not [i for i in g05(ok) if i.code == "HOOK_MISMATCH"]
    none_hook = replace_fact(ok, "f_lie_anna", exposure_hook=None)
    assert "HOOK_MISMATCH" in {i.code for i in g05(none_hook)}


def test_truthful_facts_are_never_checked_for_exposure():
    assert g05(replace_fact(build_case(), "f_alibi_anna", exposed_by=())) == []


def test_group_5_runs_even_when_group_4_found_orphans():
    from tests.cases.mutations import MUTATIONS

    report = validate(MUTATIONS["EXPOSER_UNREACHABLE"].apply(build_case()), profile=Profile.CUSTOM)
    assert {
        "ORPHAN_FACT",
        "EXPOSER_UNREACHABLE",
    } <= report.codes() and 5 not in report.skipped_groups
