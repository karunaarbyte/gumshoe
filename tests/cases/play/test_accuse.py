import pytest

from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.accuse import (
    AccuseKind,
    GameNotOver,
    accuse,
    check_accusation,
    give_up,
    reveal,
    score,
)
from gumshoe.cases.play.state import Status, Triple, new_state
from tests.cases.fixtures import build_case

WHO, HOW, WHY = Axis.WHO, Axis.HOW, Axis.WHY
TRUTH = Triple(who="s_boris", how="m_poison", why="v_debt")


def everything():
    case = build_case()
    return CaseIndex.of(case), new_state(case).with_facts(f.id for f in case.facts)


def holding(*fact_ids):
    case = build_case()
    return CaseIndex.of(case), new_state(case).with_facts(fact_ids)


def test_with_nothing_held_nobody_can_be_named():
    ix, state = holding()
    check = check_accusation(ix, state, TRUTH)
    assert check.blocked == (WHO, HOW, WHY) and check.warned == () and not check.repeat


def test_a_lead_permits_naming_and_a_lie_rule_out_warns_until_it_is_exposed():
    ix, state = holding("f_proof_boris", "f_lie_boris")
    check = check_accusation(ix, state, TRUTH)
    assert check.blocked == (HOW, WHY) and check.warned == (WHO,)
    # exposer held
    ix, state = holding("f_proof_boris", "f_lie_boris", "f_secret_boris")
    check = check_accusation(ix, state, TRUTH)
    assert check.blocked == (HOW,) and check.warned == ()


def test_eliminating_everyone_else_permits_the_last_candidate():
    ix, state = holding("f_alibi_anna", "f_clara_keys")
    check = check_accusation(ix, state, TRUTH)
    assert check.blocked == (HOW, WHY) and check.warned == ()


def test_a_candidate_off_its_axis_is_a_programming_error():
    ix, state = holding()
    with pytest.raises(ValueError):
        check_accusation(ix, state, Triple(who="m_poison", how="m_poison", why="v_debt"))


def test_score_counts_matching_parts():
    ix, _ = everything()
    assert score(ix, TRUTH) == 3
    assert (
        score(
            ix,
            Triple(who="s_boris", how="m_dagger", why="v_jealousy"),
        )
        == 1
    )
    assert (
        score(
            ix,
            Triple(who="s_anna", how="m_dagger", why="v_jealousy"),
        )
        == 0
    )


def test_an_unconfirmed_accusation_asks_for_confirmation_and_costs_nothing():
    ix, state = everything()
    after, result = accuse(ix, state, TRUTH)
    assert result.kind is AccuseKind.NEEDS_CONFIRMATION and after == state


def test_a_blocked_accusation_costs_nothing_even_when_confirmed():
    ix, state = holding()
    after, result = accuse(ix, state, TRUTH, confirmed=True)
    assert result.kind is AccuseKind.NOT_PERMITTED and after.attempts == 0


def test_the_truth_wins_and_ends_the_game():
    ix, state = everything()
    after, result = accuse(ix, state, TRUTH, confirmed=True)
    assert result.kind is AccuseKind.RESOLVED and result.correct == 3
    assert after.status is Status.WON and after.attempts == 1
    again, over = accuse(ix, after, TRUTH, confirmed=True)
    assert over.kind is AccuseKind.GAME_OVER and again == after


def test_a_wrong_accusation_reports_only_a_count_and_uses_an_attempt():
    ix, state = everything()
    after, result = accuse(
        ix,
        state,
        Triple(who="s_boris", how="m_dagger", why="v_jealousy"),
        confirmed=True,
    )
    assert result.correct == 1 and after.attempts == 1 and after.status is Status.PLAYING
    assert after.accusations[0].correct == 1


def test_an_identical_repeat_is_refused_at_no_cost():
    ix, state = everything()
    wrong = Triple(who="s_anna", how="m_dagger", why="v_jealousy")
    state, _ = accuse(ix, state, wrong, confirmed=True)
    after, result = accuse(ix, state, wrong, confirmed=True)
    assert result.kind is AccuseKind.REPEAT and after.attempts == 1


def test_the_third_miss_loses_and_attempts_never_exceed_three():
    ix, state = everything()
    misses = [
        Triple(who="s_anna", how="m_dagger", why="v_jealousy"),
        Triple(who="s_clara", how="m_rope", why="v_inheritance"),
        Triple(who="s_anna", how="m_rope", why="v_jealousy"),
    ]
    for triple in misses:
        state, result = accuse(ix, state, triple, confirmed=True)
        assert result.kind is AccuseKind.RESOLVED and result.correct == 0
    assert state.status is Status.LOST and state.attempts == 3
    after, over = accuse(ix, state, TRUTH, confirmed=True)
    assert over.kind is AccuseKind.GAME_OVER and after.attempts == 3


def test_give_up_loses_and_reveal_is_refused_until_the_game_is_over():
    ix, state = everything()
    with pytest.raises(GameNotOver):
        reveal(ix, state)
    over = give_up(state)
    assert over.status is Status.LOST and give_up(over) == over
    assert reveal(ix, over).who == "s_boris"
