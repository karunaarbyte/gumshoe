import pytest

from gumshoe.cases.play.session import BadAnswers, GameSession, NoAccusationPrompt
from gumshoe.cases.play.views import AccusationQuestions, QuestionView
from tests.cases.fixtures import build_case
from tests.cases.play.test_session_accuse import handles, s_all


def letter_for(questions, axis, fragment):
    """The option letter whose criteria text names the candidate (read like a decider would)."""
    return next(k for k, v in questions.questions[axis].criteria.items() if fragment in v)


def other_letter(questions, axis, letter):
    return next(k for k in questions.questions[axis].criteria if k != letter)


def confident(questions, axis, fragment):
    letter = letter_for(questions, axis, fragment)
    return {letter: 0.9, other_letter(questions, axis, letter): 0.05}


def test_the_questions_are_plain_views_with_no_keys_in_them():
    s = s_all()
    q = s.accusation_questions("Boris poisoned the wine to pay his debt")
    assert isinstance(q, AccusationQuestions) and q.state.startswith("The player said:")
    assert set(q.questions) == {"who", "how", "why"}
    assert all(isinstance(v, QuestionView) for v in q.questions.values())
    assert "h_" not in q.model_dump_json()  # no handle, so no letter-to-handle key can leak


def test_at_the_start_only_who_is_asked_and_it_names_no_hidden_candidate():
    s = GameSession(build_case(), "salt")
    q = s.accusation_questions("it was the rope, out of jealousy")
    assert set(q.questions) == {"who"}
    text = q.model_dump_json().lower()
    assert "poison" not in text and "debt" not in text


def test_confident_letters_resolve_to_the_named_candidates():
    s = s_all()
    q = s.accusation_questions("Boris poisoned the wine to cover a gambling debt")
    probabilities = {
        "who": confident(q, "who", "Boris"),
        "how": confident(q, "how", "poisoned in the wine"),
        "why": confident(q, "why", "gambling debt"),
    }
    assert s.interpret_probabilities(probabilities) == handles(s)


def test_a_low_confidence_pick_is_none_and_the_unclear_option_is_none():
    s = s_all()
    q = s.accusation_questions("maybe Boris?")
    letter = letter_for(q, "who", "Boris")
    unclear = letter_for(q, "how", "does not clearly")
    parsed = s.interpret_probabilities(
        {
            "who": {letter: 0.5, other_letter(q, "who", letter): 0.4},
            "how": {unclear: 0.95},
        }
    )
    assert (parsed.who, parsed.how, parsed.why) == (None, None, None)


def test_the_prompt_is_used_once_and_then_gone():
    s = s_all()
    q = s.accusation_questions("Boris")
    s.interpret_probabilities({"who": confident(q, "who", "Boris")})
    with pytest.raises(NoAccusationPrompt):
        s.interpret_probabilities({"who": confident(q, "who", "Boris")})


def test_no_prompt_yet_is_no_accusation_prompt():
    with pytest.raises(NoAccusationPrompt):
        s_all().interpret_probabilities({})


def test_a_later_call_replaces_the_stored_prompt():
    """An accusation reshuffles the letters (Clara moves from C to B on this case), so answering
    the new questions against the old prompt would read B as the unclear option."""
    s = s_all()
    old = s.accusation_questions("Clara")
    s.accuse(handles(s, who="Anna"), confirmed=True)
    new = s.accusation_questions("Clara")
    assert letter_for(old, "who", "Clara") != letter_for(new, "who", "Clara")
    parsed = s.interpret_probabilities({"who": confident(new, "who", "Clara")})
    assert parsed.who == handles(s, who="Clara").who


@pytest.mark.parametrize(
    "bad",
    [
        {"nope": {"A": 0.9}},  # an axis nobody was asked about
        {"who": {"ZZ": 0.9}},  # a letter that is not an option
        {"who": {"A": 1.5}},  # outside [0, 1]
        {"who": {"A": -0.1}},
        {"who": {"A": float("nan")}},
    ],
)
def test_bad_answers_are_refused_and_keep_the_prompt(bad):
    s = s_all()
    q = s.accusation_questions("Boris")
    with pytest.raises(BadAnswers):
        s.interpret_probabilities(bad)
    s.interpret_probabilities({"who": confident(q, "who", "Boris")})  # the prompt is still there


def test_suspects_resolve_at_the_start_because_they_are_public():
    """`_visible` is a defence; how/why candidates the gate has not opened are not asked."""
    s = GameSession(build_case(), "salt")
    q = s.accusation_questions("Boris")
    letter = letter_for(q, "who", "Boris")
    assert s.interpret_probabilities({"who": {letter: 0.9}}).who is not None  # suspects are public
