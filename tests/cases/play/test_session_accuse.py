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


def test_a_blocked_part_is_reported_as_not_permitted_with_the_nameable_options():
    s = GameSession(build_case(), "salt")
    study = next(x.handle for x in s.brief().locations if x.name == "The study")
    s.search(study)
    full = s_all()
    triple = handles(full)  # handles for the *other* session share the salt, so they match
    plan = s.describe_accusation(triple)
    assert not plan.can_confirm
    assert {p.axis: p.reason for p in plan.problems} == {"why": "not_permitted"}


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
