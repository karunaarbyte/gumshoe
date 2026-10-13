from gumshoe.agent.accuse import missing_text, probabilities_of, to_choice_questions
from gumshoe.cases import AccusationPlan, AccusationQuestions
from gumshoe.cases.play.views import AxisProblem, Candidate, QuestionView, ResolvedPart
from gumshoe.decider import DecisionResult
from tests.agent.fakes import choice, criteria_of, noul


def test_questions_become_choice_questions_with_the_same_text():
    aq = AccusationQuestions(
        state="The player said: x",
        questions={"who": QuestionView(instructions="Which?", criteria={"A": "a", "B": "b"})},
    )
    questions = to_choice_questions(aq)
    assert questions["who"].instructions == "Which?"
    assert criteria_of(questions["who"]) == {"A": "a", "B": "b"}


def test_probabilities_take_choice_answers_only():
    result = DecisionResult(
        model="m", answers={"who": choice(["A", "B"], "A", 0.75), "other": noul(0.5)}
    )
    assert probabilities_of(result) == {"who": {"A": 0.75, "B": 0.25}}


def test_missing_text_names_the_axes_and_what_may_be_named():
    plan = AccusationPlan(
        resolved=(ResolvedPart(axis="who", name="Berta"),),
        problems=(
            AxisProblem(
                axis="how",
                reason="unclear",
                options=(Candidate(handle="h1", name="the poison"),),
            ),
            AxisProblem(axis="why", reason="unclear", options=()),
        ),
        warnings=(),
        repeat=False,
        can_confirm=False,
        confirmation="",
    )
    text = missing_text(plan)
    assert "how" in text and "why" in text and "the poison" in text and "Berta" not in text
