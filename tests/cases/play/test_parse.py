import pytest

from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.parse import accusation_questions, interpret
from gumshoe.decider import ChoiceAnswer, DecisionResult
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_in

IX = CaseIndex.of(build_case())


def handle_of(entity_id):
    return f"h_{entity_id}"


def prompt(n=0, text="Boris did it"):
    return accusation_questions(IX, handle_of, n, text)


def answer(letter, probabilities):
    return ChoiceAnswer(
        type="choice", choice=letter, probabilities=probabilities, confidence=probabilities[letter]
    )


def result(prompt_, picks):
    """picks: axis -> (candidate handle or None, top probability, runner-up probability)."""
    answers = {}
    for axis, (target, top, second) in picks.items():
        keymap = prompt_.keys[axis]
        letter = next(k for k, v in keymap.items() if v == target)
        other = next(k for k in keymap if k != letter)
        answers[axis] = answer(letter, {letter: top, other: second})
    return DecisionResult(model="fake", answers=answers)


def test_each_axis_has_one_option_per_candidate_plus_one_unclear():
    p = prompt()
    assert set(p.questions) == {"who", "how", "why"}
    for axis in Axis:
        keymap = p.keys[axis.value]
        assert len(keymap) == len(IX.candidates[axis]) + 1
        assert set(p.questions[axis.value].criteria) == set(keymap)
        assert sum(1 for v in keymap.values() if v is None) == 1
        assert sorted(keymap) == [chr(ord("A") + i) for i in range(len(keymap))]
    assert "Boris the steward" in " ".join(p.questions["who"].criteria.values())
    assert p.state == "The player said: Boris did it"


def test_keys_are_deterministic_and_reshuffle_with_the_accusation_count():
    assert prompt(0) == prompt(0)
    assert prompt(0).keys != prompt(1).keys  # different shuffle (checked on this case)


def test_a_confident_clear_answer_resolves_to_the_handle():
    p = prompt()
    r = result(
        p,
        {
            "who": ("h_s_boris", 0.9, 0.05),
            "how": ("h_m_poison", 0.8, 0.1),
            "why": ("h_v_debt", 0.7, 0.2),
        },
    )
    assert interpret(p, r) == {Axis.WHO: "h_s_boris", Axis.HOW: "h_m_poison", Axis.WHY: "h_v_debt"}


def test_low_confidence_near_ties_and_the_unclear_option_all_give_none():
    p = prompt()
    r = result(
        p,
        {
            "who": ("h_s_boris", 0.55, 0.1),  # top not above 0.6
            "how": ("h_m_poison", 0.7, 0.6),  # margin not above 0.25
            "why": (None, 0.95, 0.01),  # the unclear option wins
        },
    )
    assert interpret(p, r) == {Axis.WHO: None, Axis.HOW: None, Axis.WHY: None}


def test_a_missing_or_foreign_answer_is_none():
    p = prompt()
    r = DecisionResult(model="fake", answers={"who": answer("Z", {"Z": 0.99, "Y": 0.0})})
    assert interpret(p, r) == {Axis.WHO: None, Axis.HOW: None, Axis.WHY: None}


def test_jev_criteria_never_carry_the_display_name():
    case = replace_in(build_case(), "suspects", "s_boris", display_name="Bobby")
    p = accusation_questions(CaseIndex.of(case), handle_of, 0, "Bobby did it")
    criteria = " ".join(p.questions["who"].criteria.values())
    assert "Boris the steward" in criteria and "Bobby" not in criteria


def test_more_options_than_letters_is_a_programming_error():
    many = tuple(
        build_case().methods[0].model_copy(update={"id": f"m_{i}", "label": f"way {i}"})
        for i in range(26)
    )
    ix = CaseIndex.of(build_case().model_copy(update={"methods": many}))
    with pytest.raises(AssertionError):
        accusation_questions(ix, handle_of, 0, "x")
