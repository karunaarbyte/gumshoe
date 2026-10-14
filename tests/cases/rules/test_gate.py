import random

import pytest

from gumshoe.cases.model.entities import Effect
from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.rules.gate import Permission, exposed, lead, permission
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact
from tests.cases.model.builders import tiny_case

ix = CaseIndex.of(build_case())
WHO, HOW, WHY = Axis.WHO, Axis.HOW, Axis.WHY


def held(*ids: str) -> frozenset[str]:
    return frozenset(ids)


def test_exposed_needs_both_the_lie_and_an_exposer_held():
    assert exposed(ix, held()) == frozenset()
    assert exposed(ix, held("f_lie_boris")) == frozenset()
    assert (
        exposed(ix, held("f_secret_boris")) == frozenset()
    )  # exposer alone: no lie held, nothing to mark
    assert exposed(ix, held("f_lie_boris", "f_secret_boris")) == {"f_lie_boris"}
    assert exposed(ix, held("f_lie_boris", "f_secret_anna")) == frozenset()  # the wrong exposer
    assert (
        exposed(ix, held("f_alibi_anna", "f_secret_anna")) == frozenset()
    )  # truthful facts are never "exposed"


def warned(held_ids: frozenset[str], candidate: str) -> bool:
    """The warning flag is exactly "a held rule-out against this candidate"."""
    return permission(ix, held_ids, WHO, candidate).warn


def test_held_rule_out_counts_truthful_and_unexposed_lies_alike():
    assert warned(held("f_alibi_anna"), "s_anna")
    assert warned(held("f_lie_anna"), "s_anna")
    assert not warned(held("f_alibi_anna"), "s_boris")
    assert not warned(held(), "s_anna")


def test_an_exposed_lie_stops_counting_as_a_held_rule_out():
    assert warned(held("f_lie_boris"), "s_boris")
    assert not warned(held("f_lie_boris", "f_secret_boris"), "s_boris")
    # the truthful alibi still counts after unrelated exposures
    assert warned(held("f_alibi_anna", "f_lie_anna", "f_secret_anna"), "s_anna")


def test_lead_is_any_held_supports_or_proves_including_lie_sourced():
    assert lead(ix, held("f_sup_boris"), WHO, "s_boris")
    assert lead(ix, held("f_proof_boris"), WHO, "s_boris")
    assert not lead(ix, held("f_alibi_anna"), WHO, "s_anna")  # a rule-out is not a lead
    assert not lead(ix, held(), WHY, "v_debt")
    case = replace_fact(
        build_case(),
        "f_lie_anna",
        effects=(Effect(axis=WHO, candidate="s_clara", kind=EffectKind.SUPPORTS),),
    )
    assert lead(
        CaseIndex.of(case), held("f_lie_anna"), WHO, "s_clara"
    )  # a framing lie is a visible lead


def test_permission_by_lead():
    assert permission(ix, held("f_sup_boris"), WHO, "s_boris") == Permission(
        allowed=True, warn=False
    )
    assert permission(ix, held(), WHO, "s_boris") == Permission(allowed=False, warn=False)


def test_permission_by_elimination_ignores_the_targets_own_rule_outs():
    both_others = held("f_alibi_anna", "f_clara_keys")
    assert permission(ix, both_others, WHO, "s_boris") == Permission(allowed=True, warn=False)
    # one of the others is not ruled out: no permission
    assert not permission(ix, held("f_alibi_anna"), WHO, "s_boris").allowed
    # the culprit's own unexposed false alibi never blocks naming him, it only warns
    with_lie = held("f_alibi_anna", "f_clara_keys", "f_lie_boris")
    assert permission(ix, with_lie, WHO, "s_boris") == Permission(allowed=True, warn=True)


def test_the_warning_is_identical_for_truthful_and_lying_rule_outs():
    truthful = permission(ix, held("f_alibi_anna", "f_sup_anna"), WHO, "s_anna")
    lying = permission(ix, held("f_lie_anna", "f_sup_anna"), WHO, "s_anna")
    assert truthful == lying == Permission(allowed=True, warn=True)


def test_exposed_lies_do_not_count_toward_eliminating_the_others():
    # Anna's lie is exposed, so Anna is no longer visibly ruled out: Boris still lacks permission
    state = held("f_lie_anna", "f_secret_anna", "f_clara_keys")
    assert not permission(ix, state, WHO, "s_boris").allowed
    # unexposed, her lie rules her out visibly: now the others are all ruled out
    assert permission(ix, held("f_lie_anna", "f_clara_keys"), WHO, "s_boris").allowed


def test_when_everyone_holds_a_rule_out_everyone_is_permitted_with_a_warning():
    state = held("f_lie_anna", "f_lie_boris", "f_lie_clara")
    for suspect in ("s_anna", "s_boris", "s_clara"):
        assert permission(ix, state, WHO, suspect) == Permission(allowed=True, warn=True)


def test_a_single_candidate_axis_has_no_elimination_path():
    tiny = CaseIndex.of(tiny_case())
    assert not permission(tiny, held(), HOW, "m_x").allowed


ROUTES = {
    WHO: ("s_boris", [{"f_proof_boris"}, {"f_alibi_anna", "f_clara_keys"}]),
    HOW: ("m_poison", [{"f_trace_poison"}, {"f_absent_dagger", "f_absent_rope"}]),
    WHY: ("v_debt", [{"f_secret_boris"}, {"f_ruleout_jealousy", "f_ruleout_inheritance"}]),
}


@pytest.mark.parametrize("axis", [WHO, HOW, WHY])
def test_monotonicity_adding_facts_never_removes_permission_to_name_the_truth(axis):
    truth, routes = ROUTES[axis]
    everything = sorted(ix.facts)
    rng = random.Random(20261001)
    for route in routes:
        assert permission(ix, frozenset(route), axis, truth).allowed
        for _ in range(300):
            extra = {f for f in everything if rng.random() < 0.4}
            assert permission(ix, frozenset(route | extra), axis, truth).allowed, (
                route,
                sorted(extra),
            )


def test_permission_never_reads_truthfulness_only_exposure_state():
    # flipping a lie to truthful changes nothing about who is warned
    state = held("f_alibi_anna", "f_clara_keys", "f_lie_boris")
    assert permission(ix, state, WHO, "s_boris").warn is True
    flipped = CaseIndex.of(replace_fact(build_case(), "f_lie_boris", truthful=True))
    assert permission(flipped, state, WHO, "s_boris").warn is True
