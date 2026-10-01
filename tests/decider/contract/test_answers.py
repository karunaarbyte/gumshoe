import pytest

from gumshoe.decider.contract.answers import answer_confidence, answer_verdict
from gumshoe.decider.contract.models import ChoiceAnswer, NoulAnswer, ScoreAnswer


def test_choice_and_score_confidence_come_from_the_api():
    choice = ChoiceAnswer(type="choice", choice="a", probabilities={"a": 1.0}, confidence=0.94)
    score = ScoreAnswer(type="score", score=1.2, legend={}, probabilities={}, confidence=0.4)
    assert answer_confidence(choice) == 0.94
    assert answer_confidence(score) == 0.4


@pytest.mark.parametrize(
    ("p", "expected"), [(0.5, 0.5), (0.9, 0.9), (0.1, 0.9), (1.0, 1.0), (0.0, 1.0)]
)
def test_noul_confidence_is_distance_from_a_coin_flip(p, expected):
    assert answer_confidence(NoulAnswer(type="noul", noul=p)) == pytest.approx(expected)


def test_verdicts_are_short_and_readable():
    choice = ChoiceAnswer(type="choice", choice="dialogue", probabilities={}, confidence=1.0)
    assert answer_verdict(choice) == "dialogue"
    assert answer_verdict(NoulAnswer(type="noul", noul=0.7)) == "yes"
    assert answer_verdict(NoulAnswer(type="noul", noul=0.3)) == "no"
    score = ScoreAnswer(type="score", score=1.234, legend={}, probabilities={}, confidence=1.0)
    assert answer_verdict(score) == "1.23"
