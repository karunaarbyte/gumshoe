import pytest

from gumshoe.cases.play.session import GameNotOver, GameOver, GameSession
from gumshoe.cases.play.views import ParsedAccusation
from gumshoe.decider import ChoiceAnswer, DecisionResult
from tests.cases.fixtures import build_case


def s_all():
    """A session that has used every source (everything is held)."""
    s = GameSession(build_case(), "salt")
    brief = s.brief()
    for _ in range(2):  # the cellar opens once the garden has been searched
        for loc in brief.locations:
            s.search(loc.handle)
    for sus in brief.suspects:
        s.interrogate(sus.handle)
    for loc in brief.locations:
        s.check_records(loc.handle)
    for sus in brief.suspects:
        s.check_records(sus.handle)
    return s


def handles(s, who="Boris", how="poisoned in the wine", why="to cover a gambling debt"):
    """Candidate handles by name, read through the only public door: nameable()."""
    pick = {}
    for axis, name in (("who", who), ("how", how), ("why", why)):
        pick[axis] = next(o.handle for o in s.nameable(axis).options if o.name == name)
    return ParsedAccusation(**pick)


def test_at_the_start_nothing_is_nameable():
    s = GameSession(build_case(), "salt")
    assert all(s.nameable(axis).options == () for axis in ("who", "how", "why"))


def test_nameable_lists_permitted_candidates_sorted_and_flags_warnings():
    s = s_all()
    who = s.nameable("who")
    assert [o.name for o in who.options] == ["Anna", "Boris", "Clara"]
    assert [o.warned for o in who.options] == [True, False, True]


def test_match_label_returns_a_handle_and_none_for_hedges():
    s = s_all()
    boris = handles(s).who
    assert s.match_label("who", "I accuse Boris") == boris
    assert s.match_label("who", "it wasn't Boris") is None


def test_a_confirmable_plan_shows_names_warnings_and_the_cost():
    s = s_all()
    wrong = handles(s, who="Anna")
    plan = s.describe_accusation(wrong)
    assert plan.can_confirm and not plan.repeat and plan.problems == ()
    assert [p.name for p in plan.resolved][0] == "Anna"
    assert plan.warnings == ("You hold an alibi or clue against Anna. Name them anyway?",)
    assert "3 remaining attempts" in plan.confirmation


def test_a_plan_with_an_unresolved_part_lists_what_may_be_named_and_cannot_confirm():
    s = GameSession(build_case(), "salt")
    plan = s.describe_accusation(ParsedAccusation())
    assert not plan.can_confirm and plan.confirmation == ""
    assert [p.reason for p in plan.problems] == ["unclear", "unclear", "unclear"]
    assert all(p.options == () for p in plan.problems)


def test_a_blocked_who_is_reported_as_not_permitted_with_the_nameable_options():
    s = GameSession(build_case(), "salt")
    study = next(x.handle for x in s.brief().locations if x.name == "The study")
    s.search(study)
    full = s_all()
    triple = handles(full, who="Anna")  # the other session shares the salt, so handles match
    plan = s.describe_accusation(triple)
    assert not plan.can_confirm
    # who is public, so a blocked suspect says so; a blocked motive looks like no answer
    assert {p.axis: p.reason for p in plan.problems} == {"who": "not_permitted", "why": "unclear"}
    assert [o.name for o in plan.problems[0].options] == ["Boris"]


def test_unconfirmed_blocked_repeat_and_half_filled_accusations_cost_nothing():
    s = s_all()
    parsed = handles(s, who="Anna")
    assert s.accuse(parsed).status == "needs_confirmation" and s.attempts_left == 3
    assert s.accuse(ParsedAccusation(who=parsed.who)).status == "not_permitted"
    bogus = ParsedAccusation(who="h_bogus", how="h_bogus", why="h_bogus")
    assert s.accuse(bogus).status == "not_permitted"
    assert s.attempts_left == 3
    first = s.accuse(parsed, confirmed=True)
    assert first.status == "resolved" and first.message.endswith("right.") and s.attempts_left == 2
    again = s.accuse(parsed, confirmed=True)
    assert again.status == "repeat" and s.attempts_left == 2


def test_feedback_is_a_count_only_and_the_truth_wins():
    s = s_all()
    result = s.accuse(handles(s, who="Anna", how="stabbed with a dagger"), confirmed=True)
    assert result.correct == 1 and result.game == "playing"
    assert "stabbed" not in result.message and "Anna" not in result.message
    win = s.accuse(handles(s), confirmed=True)
    assert win.correct == 3 and win.game == "won" and "solved" in win.message
    with pytest.raises(GameOver):
        s.accuse(handles(s), confirmed=True)


def test_three_misses_lose_and_the_reveal_names_the_truth_only_afterwards():
    s = s_all()
    with pytest.raises(GameNotOver):
        s.reveal()
    misses = [
        handles(s, who="Anna", how="stabbed with a dagger", why="out of jealousy"),
        handles(s, who="Clara", how="strangled with a rope", why="to claim an inheritance"),
        handles(s, who="Anna", how="strangled with a rope", why="out of jealousy"),
    ]
    for parsed in misses:
        s.accuse(parsed, confirmed=True)
    assert s.status == "lost" and s.attempts_left == 0
    reveal = s.reveal()
    assert (reveal.culprit, reveal.method, reveal.motive) == (
        "Boris",
        "poisoned in the wine",
        "to cover a gambling debt",
    )
    assert reveal.secret == "Boris gambles beyond his means."


def test_give_up_ends_the_game_and_allows_the_reveal():
    s = s_all()
    s.give_up()
    assert s.reveal().culprit == "Boris"


def test_the_jev_path_builds_questions_and_interprets_a_fake_result():
    s = s_all()
    prompt = s.accusation_prompt("Boris poisoned the wine to pay his debt")
    assert set(prompt.questions) == {"who", "how", "why"}
    want = handles(s)
    answers = {}
    for axis in ("who", "how", "why"):
        keymap = prompt.keys[axis]
        letter = next(k for k, v in keymap.items() if v == getattr(want, axis))
        other = next(k for k in keymap if k != letter)
        answers[axis] = ChoiceAnswer(
            type="choice", choice=letter, probabilities={letter: 0.9, other: 0.05}, confidence=0.9
        )
    parsed = s.interpret(prompt, DecisionResult(model="fake", answers=answers))
    assert parsed == want


def test_no_accusation_view_names_the_truth_unless_the_player_chose_it():
    s = GameSession(build_case(), "salt")
    blob = (
        s.describe_accusation(ParsedAccusation()).model_dump_json()
        + s.nameable("how").model_dump_json()
    )
    assert "poison" not in blob and "debt" not in blob


def test_a_warned_but_permitted_accusation_reaches_resolved():
    s = s_all()
    anna = handles(s, who="Anna")
    assert s.describe_accusation(anna).warnings
    result = s.accuse(anna, confirmed=True)
    assert result.status == "resolved" and result.correct == 2 and s.attempts_left == 2


@pytest.mark.parametrize("misses", [1, 2])
def test_the_truth_on_attempt_two_or_three_wins(misses):
    s = s_all()
    wrong = [
        handles(s, who="Anna", how="stabbed with a dagger", why="out of jealousy"),
        handles(s, who="Clara", how="strangled with a rope", why="to claim an inheritance"),
    ]
    for parsed in wrong[:misses]:
        s.accuse(parsed, confirmed=True)
    win = s.accuse(handles(s), confirmed=True)
    assert win.status == "resolved" and win.correct == 3 and s.status == "won"
    assert s.attempts_left == 3 - (misses + 1)


# -- hidden how/why candidates are indistinguishable from nonsense (no probing) -------------


def fresh_with_study():
    """Only the study searched: Boris and the poison are nameable, no motive is."""
    s = GameSession(build_case(), "salt")
    s.search(next(x.handle for x in s.brief().locations if x.name == "The study"))
    return s


def hidden_handles():
    """Handles of the rope and the debt, read from a session where they are nameable (same
    salt, so the same handles): a player could only have them by probing."""
    full = s_all()
    rope = next(o.handle for o in full.nameable("how").options if o.name.startswith("strangled"))
    debt = next(o.handle for o in full.nameable("why").options if o.name.endswith("debt"))
    return rope, debt


def test_typed_hidden_how_and_why_names_answer_like_nonsense_until_the_gate_opens():
    s = fresh_with_study()
    rope, debt = hidden_handles()
    for axis, text in (("how", "the rope"), ("why", "the debt")):
        assert s.match_label(axis, text) is None
        assert s.match_label(axis, "xyzzy") is None
    garden = next(x.handle for x in s.brief().locations if x.name == "The garden")
    study = next(x.handle for x in s.brief().locations if x.name == "The study")
    s.check_records(garden)  # the gate log supports the rope: now it may be named
    s.check_records(study)  # ... and the moneylender's note the debt
    assert s.match_label("how", "the rope") == rope
    assert s.match_label("why", "the debt") == debt


def test_a_hidden_how_or_why_handle_is_described_and_refused_like_an_unknown_one():
    s = fresh_with_study()
    rope, debt = hidden_handles()
    boris, poison = handles_now(s)
    for hidden, bogus in (
        (ParsedAccusation(who=boris, how=rope), ParsedAccusation(who=boris, how="h_bogus")),
        (
            ParsedAccusation(who=boris, how=poison, why=debt),
            ParsedAccusation(who=boris, how=poison, why="h_bogus"),
        ),
    ):
        assert s.describe_accusation(hidden) == s.describe_accusation(bogus)
        assert s.accuse(hidden, confirmed=True) == s.accuse(bogus, confirmed=True)
    plan = s.describe_accusation(ParsedAccusation(who=boris, how=poison, why=debt))
    assert {p.axis: p.reason for p in plan.problems} == {"why": "unclear"}
    assert s.attempts_left == 3


def test_a_hidden_candidate_is_not_an_option_until_the_gate_opens():
    s = fresh_with_study()
    rope, _ = hidden_handles()
    assert rope not in s.accusation_prompt("he strangled him with a rope").keys["how"].values()
    s.check_records(next(x.handle for x in s.brief().locations if x.name == "The garden"))
    prompt = s.accusation_prompt("he strangled him with a rope")
    keymap = prompt.keys["how"]
    letter = next(k for k, v in keymap.items() if v == rope)
    other = next(k for k in keymap if k != letter)
    answer = ChoiceAnswer(
        type="choice", choice=letter, probabilities={letter: 0.95, other: 0.0}, confidence=0.95
    )
    assert s.interpret(prompt, DecisionResult(model="fake", answers={"how": answer})).how == rope


def handles_now(s):
    who = next(o.handle for o in s.nameable("who").options if o.name == "Boris")
    how = next(o.handle for o in s.nameable("how").options if o.name == "poisoned in the wine")
    return who, how


def test_a_hidden_candidate_in_the_text_does_not_change_the_answer():
    """ "poison rope" must answer like "poison xyzzy": a hidden rope cannot make it ambiguous."""
    s = fresh_with_study()
    poison = next(o.handle for o in s.nameable("how").options if o.name.startswith("poisoned"))
    assert s.match_label("how", "poison xyzzy") == poison
    assert s.match_label("how", "poison rope") == poison


def test_the_accusation_prompt_never_lists_a_hidden_candidate():
    """The prompt is public API: it must not name a how or why the gate has not opened."""
    s = fresh_with_study()
    prompt = s.accusation_prompt("it was the rope, out of jealousy")
    text = " ".join(c for q in prompt.questions.values() for c in q.criteria.values()).lower()
    assert "poison" in text  # the permitted method is still offered
    assert "rope" not in text and "strangl" not in text and "jealous" not in text
    assert "why" not in prompt.questions  # no motive is nameable yet: nothing to ask
