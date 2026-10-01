from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact, replace_in
from tests.cases.mutations import MUTATIONS


def g10(case):
    return [i for i in validate(case, profile=Profile.CUSTOM).issues if i.group == 10]


def test_fixture_persona_data_is_consistent():
    assert g10(build_case()) == []


def test_a_secret_that_is_a_lie_is_a_mismatch():
    case = replace_fact(build_case(), "f_secret_anna", truthful=False)
    assert "SECRET_SOURCE_MISMATCH" in {i.code for i in g10(case)}


def test_a_secret_from_a_non_record_source_is_a_mismatch():
    case = replace_in(build_case(), "suspects", "s_anna", secret_fact="f_alibi_anna")
    (issue,) = [i for i in g10(case) if i.code == "SECRET_SOURCE_MISMATCH"]
    assert issue.subjects == ("s_anna", "f_alibi_anna")


def test_unspeakable_knowledge_names_the_suspect_and_fact():
    (issue,) = g10(MUTATIONS["KNOWS_NOT_SPEAKABLE"].apply(build_case()))
    assert issue.subjects == ("s_anna", "f_sup_clara")


def test_a_fact_spoken_by_the_suspect_through_another_source_is_speakable():
    case = replace_fact(
        build_case(), "f_sup_anna", speaker="s_anna"
    )  # now Anna's remark, found at Clara's source
    case = replace_in(case, "suspects", "s_anna", knows=("f_lie_anna", "f_sup_anna"))
    assert g10(case) == []


def test_the_motive_mapping_must_be_a_bijection_with_the_motives():
    (issue,) = g10(MUTATIONS["MOTIVE_MAPPING"].apply(build_case()))
    assert issue.code == "MOTIVE_MAPPING"
