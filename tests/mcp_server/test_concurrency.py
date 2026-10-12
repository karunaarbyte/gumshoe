"""The SDK runs sync tools on worker threads, so the host serialises its calls."""

import threading
import time

from gumshoe.cases.play.engine import use_source
from tests.mcp_server.helpers import explore_all, make_host


def run_threads(target, count):
    errors: list[BaseException] = []

    def guarded(index):
        try:
            target(index)
        except BaseException as exc:  # noqa: BLE001  (the test reports any failure)
            errors.append(exc)

    threads = [threading.Thread(target=guarded, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def slow_down_use_source(monkeypatch):
    """Pause between the engine reading the state and the session storing the new one, so an
    unlocked host would let two threads both build on the same old state."""

    def slow(*args, **kwargs):
        result = use_source(*args, **kwargs)
        time.sleep(0.002)
        return result

    monkeypatch.setattr("gumshoe.cases.play.session.use_source", slow)


def test_threads_sharing_one_game_find_each_fact_exactly_once(monkeypatch):
    slow_down_use_source(monkeypatch)
    host = make_host()
    new = host.new_game(1)
    game, brief = new.game, new.brief
    returned: list[int] = []

    def worker(_):
        for _round in range(4):
            for place in brief.locations:
                returned.append(len(host.search(game, place.handle).new_facts))
            for person in brief.suspects:
                returned.append(len(host.interrogate(game, person.handle).new_facts))

    assert run_threads(worker, 8) == []
    found = sum(len(s.facts) for s in host.notebook(game).sections)
    assert sum(returned) == found > 0


def test_threads_playing_their_own_games_find_what_a_lone_player_finds():
    def found(host, game):
        return sorted(f.text for section in host.notebook(game).sections for f in section.facts)

    expected = {}
    for index in range(6):
        host = make_host()
        new = host.new_game(index + 1)
        explore_all(host, new.game)
        expected[index] = found(host, new.game)
    shared = make_host()
    outcomes: dict[int, list[str]] = {}

    def worker(index):
        new = shared.new_game(index + 1)
        explore_all(shared, new.game)
        outcomes[index] = found(shared, new.game)

    assert run_threads(worker, 6) == []
    assert outcomes == expected
