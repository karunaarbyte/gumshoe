"""Small pure helpers over a single answer, shared by recording, stats and display."""

from gumshoe.decider.contract.models import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer


def answer_confidence(answer: Answer) -> float:
    """0..1. Choice/score use the API's value; noul has none, so use distance from a coin flip."""
    match answer:
        case ChoiceAnswer() | ScoreAnswer():
            return answer.confidence
        case NoulAnswer():
            return max(answer.noul, 1 - answer.noul)


def answer_verdict(answer: Answer) -> str:
    """Short readable verdict: the chosen option, yes/no, or the score to two decimals."""
    match answer:
        case ChoiceAnswer():
            return answer.choice
        case NoulAnswer():
            return "yes" if answer.yes else "no"
        case ScoreAnswer():
            return f"{answer.score:.2f}"
