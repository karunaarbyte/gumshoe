import pytest

from gumshoe.mcp_server import GameError
from tests.mcp_server.helpers import make_host

SEED = 1


def started():
    host = make_host()
    new = host.new_game(SEED)
    return host, new.game, new.brief


def first_fruitful_location(host, game, brief):
    for location in brief.locations:
        if not location.locked:
            result = host.search(game, location.handle)
            if result.status == "ok":
                return location, result
    raise AssertionError("no location gave anything")


def test_searching_a_place_returns_its_new_facts_and_a_repeat_returns_nothing_new():
    host, game, brief = started()
    location, first = first_fruitful_location(host, game, brief)
    assert first.kind == "search" and first.new_facts
    assert len(first.new_facts) <= 4
    again = host.search(game, location.handle)
    assert again.status == "nothing_new" and not again.new_facts


def test_a_suspect_the_gate_has_not_opened_answers_locked_and_gives_nothing():
    host = make_host()
    new = host.new_game(5)  # in this case every suspect is locked at the start
    gated = next(x for x in new.brief.suspects if x.locked)
    result = host.interrogate(new.game, gated.handle)
    assert result.status == "locked" and result.new_facts == ()


def test_interrogating_a_suspect_returns_their_statements():
    host, game, brief = started()
    result = host.interrogate(game, brief.suspects[0].handle)
    assert result.kind == "interrogate" and result.status == "ok" and result.new_facts
    assert host.interrogate(game, brief.suspects[0].handle).status == "nothing_new"


def test_records_can_be_read_by_kind_or_all_kinds_about_a_subject():
    host, game, brief = started()
    for suspect in brief.suspects:
        host.interrogate(game, suspect.handle)
    subjects = [x.handle for x in (*brief.suspects, *brief.locations)]
    everything = [host.check_records(game, handle) for handle in subjects]
    assert {r.kind for r in everything} == {"records"}
    assert any(r.status == "ok" and r.new_facts for r in everything)
    by_kind = [
        host.check_records(game, handle, kind.key)
        for handle in subjects
        for kind in brief.record_kinds
    ]
    assert {r.kind for r in by_kind} == {"records"}


@pytest.mark.parametrize("tool", ["search", "interrogate", "check_records"])
def test_an_unknown_handle_is_the_engines_unknown_status_not_an_error(tool):
    host, game, _ = started()
    assert getattr(host, tool)(game, "h_nothing").status == "unknown"


def test_the_notebook_holds_what_was_found():
    host, game, brief = started()
    _, result = first_fruitful_location(host, game, brief)
    found = {f.text for f in result.new_facts}
    notebook_texts = {f.text for s in host.notebook(game).sections for f in s.facts}
    assert found <= notebook_texts


def test_the_same_calls_on_equal_hosts_give_equal_results():
    def play():
        host, game, brief = started()
        out = [host.search(game, x.handle) for x in brief.locations]
        out += [host.interrogate(game, x.handle) for x in brief.suspects]
        return out, host.notebook(game)

    assert play() == play()


@pytest.mark.parametrize(
    "call",
    [
        lambda h: h.search("0000000000000099", "x"),
        lambda h: h.interrogate("0000000000000099", "x"),
        lambda h: h.check_records("0000000000000099", "x"),
        lambda h: h.notebook("0000000000000099"),
        lambda h: h.give_up("0000000000000099"),
        lambda h: h.reveal("0000000000000099"),
    ],
)
def test_every_action_on_an_unknown_game_is_unknown_game(call):
    with pytest.raises(GameError) as err:
        call(make_host())
    assert err.value.code == "unknown_game"


def test_reveal_while_playing_is_not_over_and_does_not_end_the_game():
    host, game, _ = started()
    with pytest.raises(GameError) as err:
        host.reveal(game)
    assert err.value.code == "not_over"
    assert host.case_brief(game).status == "playing"


def test_giving_up_loses_the_game_and_shows_the_truth_once():
    host, game, brief = started()
    revealed = host.give_up(game)
    assert revealed.culprit and revealed.method and revealed.motive and revealed.secret
    assert host.case_brief(game).status == "lost"
    assert host.reveal(game) == revealed


def test_after_the_end_the_acting_tools_say_game_over_and_the_reading_tools_still_work():
    host, game, brief = started()
    host.give_up(game)
    acting = [
        lambda: host.search(game, brief.locations[0].handle),
        lambda: host.interrogate(game, brief.suspects[0].handle),
        lambda: host.check_records(game, brief.suspects[0].handle),
        lambda: host.give_up(game),
    ]
    for call in acting:
        with pytest.raises(GameError) as err:
            call()
        assert err.value.code == "game_over"
    assert host.case_brief(game).status == "lost"
    host.notebook(game)
