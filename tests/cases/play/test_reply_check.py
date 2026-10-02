from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.reply_check import reply_check
from gumshoe.cases.play.session import GameSession
from gumshoe.cases.play.state import new_state
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact

CASE = build_case()
IX = CaseIndex.of(CASE)


def state(*held):
    return new_state(CASE).with_facts(held)


def violations(result):
    return {v.category: v.count for v in result.violations}


def test_a_reply_with_only_known_words_is_ok():
    result = reply_check(IX, state(), "s_anna", "Where were you?", "I was in the garden, Boris.")
    assert result.ok and result.violations == ()


def test_a_method_word_the_player_has_not_met_is_flagged_by_category_only():
    result = reply_check(IX, state(), "s_anna", "What do you know?", "It was the poison.")
    assert not result.ok and violations(result) == {"how": 1}


def test_the_same_word_is_fine_once_a_held_fact_says_it():
    held = state("f_sup_poison")  # "Wine was carried up from the cellar."
    assert reply_check(IX, held, "s_anna", "Tell me.", "Someone carried wine up.").ok
    flagged = reply_check(IX, state(), "s_anna", "Tell me.", "Someone carried wine up.")
    assert violations(flagged) == {"how": 1}


def test_a_word_from_an_unlocked_but_undiscovered_statement_is_allowed():
    # f_sup_boris ("I saw Boris heading for the study") is available at interrogate(anna) now
    assert reply_check(IX, state(), "s_anna", "Tell me.", "I saw Boris heading for the study.").ok


def test_a_word_the_player_said_is_allowed():
    assert reply_check(IX, state(), "s_anna", "Was it poison?", "I know nothing of poison.").ok


def test_smalltalk_words_are_allowed():
    case = CASE.model_copy(update={"smalltalk_allow": ("poison",)})
    assert reply_check(CaseIndex.of(case), state(), "s_anna", "Hi.", "Poison, you say?").ok


def test_a_motive_word_is_flagged_as_why():
    result = reply_check(IX, state(), "s_anna", "Why?", "He owed a gambling debt.")
    assert violations(result) == {"why": 1}


def test_a_legitimate_other_candidate_token_inside_an_unlocked_statement():
    # WHO-axis violations cannot fire: names and roles are always in the brief.
    case = replace_fact(CASE, "f_sup_boris", text="I saw Boris carry poison toward the study.")
    reply = "I saw Boris carry poison toward the study."
    assert reply_check(CaseIndex.of(case), state(), "s_anna", "Tell me.", reply).ok
    flagged = reply_check(IX, state(), "s_anna", "Tell me.", reply)
    assert violations(flagged) == {"how": 1}


def test_the_session_flags_an_unknown_suspect_handle():
    s = GameSession(CASE, "salt")
    result = s.check_reply("h_bogus", "Hi.", "Hello.")
    assert not result.ok and violations(result) == {"unknown_suspect": 1}
    anna = next(x.handle for x in s.brief().suspects if x.name == "Anna")
    assert s.check_reply(anna, "Hi.", "Hello.").ok
