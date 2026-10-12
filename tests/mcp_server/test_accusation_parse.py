import math

import pytest

from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.host import MAX_TEXT
from tests.mcp_server.helpers import SeqIds, castle_case, explore_all, make_host, true_triple

SEED = 1


def started():
    host = make_host()
    new = host.new_game(SEED)
    return host, new.game


def explored():
    host, game = started()
    explore_all(host, game)
    return host, game, castle_case(SEED)


def code_of(call):
    with pytest.raises(GameError) as err:
        call()
    return err.value.code


def letter_for(questions, axis, label):
    return next(k for k, v in questions.questions[axis].criteria.items() if label in v)


def confident(questions, axis, label):
    letter = letter_for(questions, axis, label)
    other = next(k for k in questions.questions[axis].criteria if k != letter)
    return {letter: 0.9, other: 0.05}


def test_at_the_start_only_who_is_asked():
    host, game = started()
    q = host.accusation_questions(game, "it was the cook")
    assert set(q.questions) == {"who"}
    assert q.state == "The player said: it was the cook"


def test_after_exploring_every_axis_is_asked_with_the_true_labels_offered():
    host, game, case = explored()
    q = host.accusation_questions(game, "I know who did it")
    assert set(q.questions) == {"who", "how", "why"}
    truth_labels = {
        "who": next(s.display_name for s in case.suspects if s.id == case.truth.who),
        "how": next(m.label for m in case.methods if m.id == case.truth.how),
        "why": next(m.label for m in case.motives if m.id == case.truth.why),
    }
    for axis, label in truth_labels.items():
        assert label in " ".join(q.questions[axis].criteria.values())


def test_confident_letters_resolve_to_the_handles_nameable_gives():
    host, game, case = explored()
    q = host.accusation_questions(game, "text")
    who, how, why = true_triple(host, game, case)
    names = {
        "who": next(c.name for c in host.nameable(game, "who").options if c.handle == who),
        "how": next(c.name for c in host.nameable(game, "how").options if c.handle == how),
        "why": next(c.name for c in host.nameable(game, "why").options if c.handle == why),
    }
    probabilities = {axis: confident(q, axis, name) for axis, name in names.items()}
    parsed = host.interpret_accusation(game, probabilities)
    assert (parsed.who, parsed.how, parsed.why) == (who, how, why)
    assert host.describe_accusation(game, parsed.who, parsed.how, parsed.why).can_confirm


def test_an_unclear_axis_comes_back_as_none():
    host, game, _ = explored()
    q = host.accusation_questions(game, "text")
    unclear = letter_for(q, "who", "does not clearly")
    parsed = host.interpret_accusation(game, {"who": {unclear: 0.95}})
    assert parsed.who is None


def test_interpreting_without_questions_or_twice_is_a_bad_argument():
    host, game, _ = explored()
    assert code_of(lambda: host.interpret_accusation(game, {})) == "bad_argument"
    q = host.accusation_questions(game, "text")
    host.interpret_accusation(game, {"who": confident(q, "who", "Alys")})
    assert code_of(lambda: host.interpret_accusation(game, {})) == "bad_argument"


@pytest.mark.parametrize(
    "bad",
    [{"nope": {"A": 0.5}}, {"who": {"ZZ": 0.5}}, {"who": {"A": 2.0}}, {"who": {"A": math.nan}}],
)
def test_bad_answers_are_a_bad_argument_and_keep_the_questions(bad):
    host, game, _ = explored()
    q = host.accusation_questions(game, "text")
    assert code_of(lambda: host.interpret_accusation(game, bad)) == "bad_argument"
    letter = letter_for(q, "who", "Alys")
    host.interpret_accusation(game, {"who": {letter: 0.9}})  # the questions are still stored


def test_an_overlong_text_is_a_bad_argument():
    host, game = started()
    assert code_of(lambda: host.accusation_questions(game, "x" * (MAX_TEXT + 1))) == "bad_argument"
    host.accusation_questions(game, "x" * MAX_TEXT)


def test_unknown_game_is_unknown_game():
    host, _ = started()
    assert code_of(lambda: host.accusation_questions("nope", "t")) == "unknown_game"
    assert code_of(lambda: host.interpret_accusation("nope", {})) == "unknown_game"


def test_the_stored_questions_do_not_survive_load_or_a_new_game(tmp_path):
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    game = host.new_game(SEED).game
    host.accusation_questions(game, "text")
    loaded = host.load_game(host.save_game(game).name).game
    assert code_of(lambda: host.interpret_accusation(loaded, {})) == "bad_argument"
    other = host.new_game(2).game
    assert code_of(lambda: host.interpret_accusation(other, {})) == "bad_argument"
    host.interpret_accusation(game, {})  # the original game still holds its questions
