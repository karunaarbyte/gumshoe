"""Helpers for the accusation flow: engine questions to decider questions, and back."""

from typing import Literal, cast

from gumshoe.agent.events import AccusationProblem, ProblemOption
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


NO_LEAD = "You don't hold a lead on anyone yet. Keep searching, questioning and reading records."


def missing_text(plan: AccusationPlan, who_name: str | None = None) -> str:
    """What is missing from an accusation. `who_name` is the suspect the player named, or None
    when the name is not theirs to know yet. Only the who axis is ever explained as a gate: a
    gated how or why reads exactly like an unknown one, so it cannot be probed."""
    blocked = next(
        (p for p in plan.problems if p.axis == "who" and p.reason == "not_permitted"), None
    )
    if blocked is not None and not blocked.options:
        return NO_LEAD
    parts = []
    for problem in plan.problems:
        names = ", ".join(c.name for c in problem.options)
        if problem is blocked:
            target = who_name if who_name is not None else "that suspect"
            parts.append(f"You have nothing on {target} yet. You can name: {names}.")
            continue
        hint = f" (you can name: {names})" if names else ""
        parts.append(f"I could not tell what you meant for the {problem.axis}{hint}.")
    return " ".join(parts)


def problems_of(plan: AccusationPlan) -> tuple[AccusationProblem, ...]:
    """The plan's problems as event data: the axis, why, and the candidates nameable now."""
    return tuple(
        AccusationProblem(
            axis=cast(Literal["who", "how", "why"], problem.axis),
            reason=cast(Literal["unclear", "not_permitted"], problem.reason),
            options=tuple(ProblemOption(handle=c.handle, name=c.name) for c in problem.options),
        )
        for problem in plan.problems
    )
