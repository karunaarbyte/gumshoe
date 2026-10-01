import pytest

from gumshoe.decider.contract.agreement import SCORE_TOLERANCE, answers_agree
from gumshoe.decider.contract.models import ChoiceAnswer, NoulAnswer, ScoreAnswer


def choice(option: str) -> ChoiceAnswer:
    return ChoiceAnswer(type="choice", choice=option, probabilities={option: 1.0}, confidence=1.0)


def noul(p: float) -> NoulAnswer:
    return NoulAnswer(type="noul", noul=p)


def score(value: float) -> ScoreAnswer:
    return ScoreAnswer(
        type="score", score=value, legend={"0": "lo", "1": "hi"}, probabilities={}, confidence=1.0
    )


def test_choices_agree_only_on_the_same_option():
    assert answers_agree([choice("action"), choice("action")])
    assert not answers_agree([choice("action"), choice("dialogue")])


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(0.9, 0.6, True), (0.1, 0.4, True), (0.9, 0.2, False), (0.5, 0.99, True), (0.49, 0.5, False)],
)
def test_noul_agrees_when_on_the_same_side_of_one_half(a, b, expected):
    assert answers_agree([noul(a), noul(b)]) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (1.30, 1.25, True),
        (2.49, 2.51, True),  # rounding would have split these across levels 2 and 3
        (1.5, 2.5, False),  # rounding (half-to-even) used to call these identical
        (1.04, 0.09, False),
        (1.0, 1.5, False),  # exactly SCORE_TOLERANCE apart counts as a disagreement
    ],
)
def test_scores_agree_within_the_tolerance(a, b, expected):
    assert SCORE_TOLERANCE == 0.5
    assert answers_agree([score(a), score(b)]) is expected


def test_three_scores_must_all_sit_within_the_tolerance():
    assert answers_agree([score(1.0), score(1.2), score(1.4)])
    assert not answers_agree([score(1.0), score(1.3), score(1.6)])  # neighbours close, ends apart


def test_mixed_answer_types_never_agree():
    assert not answers_agree([choice("a"), noul(0.9)])


def test_fewer_than_two_answers_trivially_agree():
    assert answers_agree([])
    assert answers_agree([choice("a")])
