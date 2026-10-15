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


def plan_with(*problems):
    return AccusationPlan(
        resolved=(),
        problems=problems,
        warnings=(),
        repeat=False,
        can_confirm=False,
        confirmation="",
    )


def test_a_who_with_nobody_nameable_is_one_no_lead_line_without_the_how_and_why_noise():
    plan = plan_with(
        AxisProblem(axis="who", reason="not_permitted", options=()),
        AxisProblem(axis="how", reason="unclear", options=()),
        AxisProblem(axis="why", reason="unclear", options=()),
    )
    assert missing_text(plan, "Maud the clerk") == (
        "You don't hold a lead on anyone yet. Keep searching, questioning and reading records."
    )


def test_a_who_with_others_nameable_names_who_the_player_can_pick_instead():
    plan = plan_with(
        AxisProblem(
            axis="who",
            reason="not_permitted",
            options=(Candidate(handle="h1", name="Gilbert"), Candidate(handle="h2", name="Hugh")),
        ),
    )
    text = missing_text(plan, "Maud the clerk")
    assert text == "You have nothing on Maud the clerk yet. You can name: Gilbert, Hugh."


def test_a_who_the_player_may_not_know_by_name_reads_like_one_nobody_has():
    # a locked suspect's name is a secret: guessing names must not reveal who is hidden
    gated = plan_with(AxisProblem(axis="who", reason="not_permitted", options=()))
    unknown = plan_with(AxisProblem(axis="who", reason="unclear", options=()))
    assert missing_text(gated, None) == missing_text(unknown, None)
    options = (Candidate(handle="h1", name="Gilbert"),)
    gated_with = plan_with(AxisProblem(axis="who", reason="not_permitted", options=options))
    unknown_with = plan_with(AxisProblem(axis="who", reason="unclear", options=options))
    assert missing_text(gated_with, None) == missing_text(unknown_with, None)


def test_a_gated_how_reads_exactly_like_an_unknown_one():
    # the engine reports both as `unclear` with the same options; the text must not tell them apart
    options = (Candidate(handle="h1", name="the poison"),)
    gated = plan_with(AxisProblem(axis="how", reason="unclear", options=options))
    unknown = plan_with(AxisProblem(axis="how", reason="unclear", options=options))
    assert missing_text(gated, None) == missing_text(unknown, None)
    assert "lead" not in missing_text(gated, None) and "yet" not in missing_text(gated, None)


def test_the_event_data_hides_a_locked_name_the_same_way_the_text_does():
    from gumshoe.agent.accuse import problems_of

    gated = plan_with(AxisProblem(axis="who", reason="not_permitted", options=()))
    # a name that is not the player's to know: the reason must not tell it from a made-up one
    assert problems_of(gated, None)[0].reason == "unclear"
    assert problems_of(gated, "Maud the clerk")[0].reason == "not_permitted"
    other = plan_with(AxisProblem(axis="how", reason="unclear", options=()))
    assert problems_of(other, None)[0].reason == "unclear"
