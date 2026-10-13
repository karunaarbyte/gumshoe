"""Helpers for the accusation flow: engine questions to decider questions, and back."""

from gumshoe.cases import AccusationPlan, AccusationQuestions
from gumshoe.decider import ChoiceAnswer, ChoiceQuestion, DecisionResult, Question


def to_choice_questions(aq: AccusationQuestions) -> dict[str, Question]:
    return {
        axis: ChoiceQuestion(instructions=q.instructions, criteria=dict(q.criteria))
        for axis, q in aq.questions.items()
    }


def probabilities_of(result: DecisionResult) -> dict[str, dict[str, float]]:
    """The tool argument: option letter probabilities per axis, from choice answers only."""
    return {
        name: dict(answer.probabilities)
        for name, answer in result.answers.items()
        if isinstance(answer, ChoiceAnswer)
    }


def missing_text(plan: AccusationPlan) -> str:
    parts = []
    for problem in plan.problems:
        names = ", ".join(c.name for c in problem.options)
        hint = f" (you can name: {names})" if names else ""
        parts.append(f"the {problem.axis}{hint}")
    return "I could not tell what you meant for " + "; ".join(parts) + "."
