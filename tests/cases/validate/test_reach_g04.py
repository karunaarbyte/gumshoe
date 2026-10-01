from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import drop_fact, replace_in, replace_record_source, replace_start

ix = CaseIndex.of(build_case())


def test_everything_in_the_fixture_is_reachable():
    r = compute_reach(ix)
    assert r.facts == frozenset(ix.facts) and len(r.facts) == 22
    assert r.locations == {"l_study", "l_garden", "l_cellar"}
    assert r.suspects == {"s_anna", "s_boris", "s_clara"}
    assert len(r.record_sources) == 5


def test_removing_the_key_cuts_off_the_cellar_and_its_facts():
    r = compute_reach(ix, removed=frozenset({"f_key"}))
    assert "l_cellar" not in r.locations and "f_clara_keys" not in r.facts
    assert "f_key" not in r.facts and "f_proof_boris" in r.facts


def test_a_gated_record_source_opens_when_its_requirements_are_found():
    case = replace_record_source(build_case(), "ledger", "s_boris", requires=("f_proof_boris",))
    r = compute_reach(CaseIndex.of(case))
    assert ("ledger", "s_boris") in r.record_sources and "f_secret_boris" in r.facts
    cut = compute_reach(CaseIndex.of(case), removed=frozenset({"f_proof_boris"}))
    assert "f_secret_boris" not in cut.facts and ("ledger", "s_boris") not in cut.record_sources


def test_a_location_outside_start_with_no_gate_is_unreachable():
    case = replace_start(build_case(), locations=("l_study",))
    r = compute_reach(CaseIndex.of(case))
    assert "l_garden" not in r.locations and "f_key" not in r.facts


def test_start_facts_are_discovered_without_a_source():
    case = replace_start(build_case(), facts=("f_key",))
    assert "f_key" in compute_reach(CaseIndex.of(case)).facts


def test_reach_terminates_on_cycles_and_leaves_cyclic_facts_unreachable():
    from tests.cases.helpers import replace_fact

    case = replace_fact(
        replace_fact(build_case(), "f_key", requires=("f_alibi_anna",)),
        "f_alibi_anna",
        requires=("f_key",),
    )
    r = compute_reach(CaseIndex.of(case))
    assert "f_key" not in r.facts and "f_alibi_anna" not in r.facts


def g04(case, profile=Profile.CUSTOM):
    return [i for i in validate(case, profile=profile).issues if i.group == 4]


def test_fixture_has_no_group_4_issues():
    assert g04(build_case()) == []


def test_source_cap_issue_names_the_source_and_count():
    from tests.cases.mutations import MUTATIONS

    case = MUTATIONS["SOURCE_CAP_EXCEEDED"].apply(build_case())
    (issue,) = [i for i in g04(case) if i.code == "SOURCE_CAP_EXCEEDED"]
    assert dict(issue.params)["count"] == "5" and "l_study" in issue.subjects[0]


def test_untouchable_candidate_names_the_candidate_and_axis():
    from tests.cases.mutations import MUTATIONS

    issues = [
        i
        for i in g04(MUTATIONS["UNTOUCHABLE_CANDIDATE"].apply(build_case()))
        if i.code == "UNTOUCHABLE_CANDIDATE"
    ]
    assert [i.subjects for i in issues] == [("m_rope",)] and issues[0].axis.value == "how"


def test_decorative_locations_are_exempt_from_the_orphan_and_empty_checks():
    case = replace_in(build_case(), "locations", "l_cellar", decorative=True, requires=())
    case = drop_fact(case, "f_clara_keys")  # the decorative cellar is now unreachable and empty
    codes = {i.code for i in g04(case)}
    assert "ORPHAN_ENTITY" not in codes and "EMPTY_LOCATION" not in codes
