import pytest

from gumshoe.cases.core.ids import make_id
from gumshoe.mcp_server import GameError
from tests.mcp_server.helpers import castle_case, explore_all, make_host, true_triple

SEED = 1
FIRST_SALT = "0000000000000001"  # SeqIds gives the first game its salt


def started():
    host = make_host()
    new = host.new_game(SEED)
    return host, new.game, new.brief


def explored():
    host, game, brief = started()
    explore_all(host, game)
    return host, game, brief, castle_case(SEED)


def a_wrong_who(host, game, true_who):
    return next(c.handle for c in host.nameable(game, "who").options if c.handle != true_who)


def test_nothing_can_be_named_until_the_player_has_found_something():
    host, game, _ = started()
    assert all(not host.nameable(game, axis).options for axis in ("who", "how", "why"))


def test_nameable_lists_the_candidates_the_gate_allows_sorted_by_name():
    host, game, _, _ = explored()
    for axis in ("who", "how", "why"):
        options = host.nameable(game, axis)
        assert options.axis == axis and options.options
        names = [c.name for c in options.options]
        assert names == sorted(names)


def test_exploring_opens_the_true_method_and_motive_for_naming():
    host, game, _ = started()
    case = castle_case(SEED)
    hidden = make_id("h", FIRST_SALT, case.truth.how)
    assert hidden not in {c.handle for c in host.nameable(game, "how").options}
    explore_all(host, game)
    assert hidden in {c.handle for c in host.nameable(game, "how").options}


@pytest.mark.parametrize("axis", ["", "WHO", "when", "who "])
def test_a_bad_axis_is_a_bad_argument(axis):
    host, game, _ = started()
    with pytest.raises(GameError) as err:
        host.nameable(game, axis)
    assert err.value.code == "bad_argument"


def test_describing_an_empty_accusation_lists_what_is_missing_and_confirms_nothing():
    host, game, _ = started()
    plan = host.describe_accusation(game)
    assert not plan.can_confirm and not plan.resolved
    assert {p.axis for p in plan.problems} == {"who", "how", "why"}
    assert {p.reason for p in plan.problems} == {"unclear"}


def test_describing_a_full_accusation_builds_the_confirmation_line():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    plan = host.describe_accusation(game, who, how, why)
    assert plan.can_confirm and not plan.problems and not plan.repeat
    assert plan.confirmation.startswith("Your accusation:")
    assert [r.axis for r in plan.resolved] == ["who", "how", "why"]


def test_accusing_without_confirmation_consumes_no_attempt():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    result = host.accuse(game, who, how, why)
    assert result.status == "needs_confirmation" and result.attempts_left == 3
    assert result.correct is None and result.game == "playing"


def test_a_confirmed_true_accusation_wins_and_only_the_count_is_returned():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    result = host.accuse(game, who, how, why, confirmed=True)
    assert result.status == "resolved" and result.correct == 3
    assert result.game == "won" and result.attempts_left == 2
    assert host.case_brief(game).status == "won"
    assert host.reveal(game).culprit


def test_a_wrong_accusation_reports_only_how_many_parts_were_right_and_a_repeat_is_refused():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    wrong = a_wrong_who(host, game, who)
    result = host.accuse(game, wrong, how, why, confirmed=True)
    assert result.status == "resolved" and result.correct == 2
    assert result.game == "playing" and result.attempts_left == 2
    again = host.accuse(game, wrong, how, why, confirmed=True)
    assert again.status == "repeat" and again.attempts_left == 2
    assert host.describe_accusation(game, wrong, how, why).repeat


def test_the_third_miss_loses_the_game():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    wrongs = [c.handle for c in host.nameable(game, "who").options if c.handle != who]
    for handle in wrongs[:3]:
        result = host.accuse(game, handle, how, why, confirmed=True)
    assert result.game == "lost" and result.attempts_left == 0
    assert host.case_brief(game).status == "lost"


def test_a_candidate_the_gate_has_not_opened_is_not_permitted_and_costs_nothing():
    host, game, _ = started()
    truth = castle_case(SEED).truth
    who, how, why = (make_id("h", FIRST_SALT, x) for x in (truth.who, truth.how, truth.why))
    result = host.accuse(game, who, how, why, confirmed=True)
    assert result.status == "not_permitted" and result.attempts_left == 3
    plan = host.describe_accusation(game, who, how, why)
    assert not plan.can_confirm and len(plan.problems) == 3
    assert {p.reason for p in plan.problems} <= {"unclear", "not_permitted"}
    assert host.case_brief(game).status == "playing"


@pytest.mark.parametrize("part", ["who", "how", "why"])
@pytest.mark.parametrize("bad", ["", "h_nothing"])
def test_a_missing_or_unknown_part_is_not_permitted_and_costs_nothing(part, bad):
    host, game, _, case = explored()
    parts = dict(zip(("who", "how", "why"), true_triple(host, game, case), strict=True))
    parts[part] = bad
    result = host.accuse(game, parts["who"], parts["how"], parts["why"], confirmed=True)
    assert result.status == "not_permitted" and result.attempts_left == 3
    assert host.case_brief(game).status == "playing"


def test_after_the_end_accuse_says_game_over_and_describe_cannot_confirm():
    host, game, _, case = explored()
    who, how, why = true_triple(host, game, case)
    host.accuse(game, who, how, why, confirmed=True)
    with pytest.raises(GameError) as err:
        host.accuse(game, who, how, why, confirmed=True)
    assert err.value.code == "game_over"
    assert not host.describe_accusation(game, who, how, why).can_confirm
    assert host.nameable(game, "who").options


@pytest.mark.parametrize(
    "call",
    [
        lambda h: h.nameable("0000000000000099", "who"),
        lambda h: h.describe_accusation("0000000000000099"),
        lambda h: h.accuse("0000000000000099", "a", "b", "c"),
    ],
)
def test_every_accusation_tool_on_an_unknown_game_is_unknown_game(call):
    with pytest.raises(GameError) as err:
        call(make_host())
    assert err.value.code == "unknown_game"
