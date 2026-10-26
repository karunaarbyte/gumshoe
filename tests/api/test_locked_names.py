"""The names of locked suspects and places never reach the browser, until they unlock."""

import pytest

from gumshoe.api import create_app
from gumshoe.cases import LocationView, SuspectView
from gumshoe.mcp_server import GameHost
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory

SEED = 5  # standard: every suspect starts locked, every place is open
CHAPEL = "Chapel of Saint Anne"  # searching it unlocks Thomas, and only him
THOMAS = "Thomas the bard"


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


@pytest.fixture(scope="module")
def truth():
    """The real brief of the case (the engine's own view, names and all)."""
    return GameHost().new_game(SEED).brief


def entries(brief):
    return [*brief["suspects"], *brief["locations"]]


def assert_redacted(brief, truth, still_locked):
    """Every locked entry is blank, every open one is exactly what the engine says."""
    real = {e.handle: e for e in [*truth.suspects, *truth.locations]}
    by_name = {e.name: e for e in real.values()}
    for entry in entries(brief):
        if entry["locked"]:
            assert (entry["name"], entry["description"]) == ("", "")
        else:
            original = by_name[entry["name"]]
            assert entry["description"] == original.description
    assert {e.name for e in real.values() if e.name not in names_of(brief)} == still_locked


def names_of(brief):
    return {e["name"] for e in entries(brief) if not e["locked"]}


def secrets_of(truth, still_locked):
    """The text of every still-locked entry: its name and its description."""
    found = [e for e in [*truth.suspects, *truth.locations] if e.name in still_locked]
    return [text for e in found for text in (e.name, e.description) if text]


def assert_absent(body: str, secrets):
    for secret in secrets:
        assert secret not in body, f"a locked secret reached the browser: {secret!r}"


def test_an_entry_has_no_field_the_redaction_does_not_know():
    """The redaction blanks `name` and `description`: a new text field must be decided on."""
    base = {"number", "handle", "name", "description", "locked"}
    assert set(LocationView.model_fields) == base
    assert set(SuspectView.model_fields) == base | {"revealed"}


def test_a_revealed_suspect_keeps_the_name_but_not_the_description():
    """Locked yet accusable by elimination: the picker names them, so the board may too."""
    from gumshoe.api.redact import player_brief

    def sus(n, revealed):
        return SuspectView(
            number=n,
            handle=f"s{n}",
            name=f"Name {n}",
            description="secret",
            locked=True,
            revealed=revealed,
        )

    brief = (
        GameHost()
        .new_game(SEED)
        .brief.model_copy(update={"suspects": (sus(1, True), sus(2, False))})
    )
    shown = player_brief(brief).suspects
    assert (shown[0].name, shown[0].description, shown[0].locked) == ("Name 1", "", True)
    assert (shown[1].name, shown[1].description) == ("", "")


def test_locked_names_never_reach_the_browser_until_they_unlock(store, tmp_path, truth):
    locked = {s.name for s in truth.suspects}
    assert all(s.locked for s in truth.suspects) and not any(p.locked for p in truth.locations)
    script = Script()
    app = create_app(store, make_service=fake_factory(script, saves_dir=tmp_path / "saves"))
    with TestClient(app) as client:
        created = client.post("/api/games", json={"seed": SEED})
        assert created.status_code == 200
        assert_redacted(created.json()["brief"], truth, locked)
        assert_absent(created.text, secrets_of(truth, locked))
        game = created.json()["game"]
        state = client.get(f"/api/games/{game}")
        assert_redacted(state.json()["brief"], truth, locked)
        assert_absent(state.text, secrets_of(truth, locked))

        chapel = next(p for p in created.json()["brief"]["locations"] if p["name"] == CHAPEL)
        script.understand(intent="search", target=f"place_{chapel['number']}")
        with client.stream("POST", f"/api/games/{game}/turn", json={"text": "search"}) as r:
            events = "".join(r.iter_text())
        still = locked - {THOMAS}
        assert THOMAS in events  # what the search opened is named: the case opened up
        assert_absent(events, secrets_of(truth, still))
        turns = client.get(f"/api/games/{game}/turns")
        assert_absent(turns.text, secrets_of(truth, still))

        state = client.get(f"/api/games/{game}")
        assert_redacted(state.json()["brief"], truth, still)
        assert THOMAS in names_of(state.json()["brief"])
        assert_absent(state.text, secrets_of(truth, still))

        saved = client.post(f"/api/games/{game}/save")
        loaded = client.post("/api/games/load", json={"name": saved.json()["name"]})
        assert loaded.status_code == 200
        assert_redacted(loaded.json()["brief"], truth, still)
        assert_absent(loaded.text, secrets_of(truth, still))
        assert_absent(saved.text, secrets_of(truth, still))


def play_until_revealed(seed):
    """Play a game with a fixed random strategy until a suspect is revealed; return the session."""
    import random

    rng = random.Random(seed * 1000)
    host = GameHost(max_games=10)
    session = host._games[host.new_game(seed, "standard").game].session
    for _ in range(400):
        brief = session.brief()
        if any(s.revealed for s in brief.suspects):
            return session
        moves = [("search", p.handle) for p in brief.locations if not p.locked]
        moves += [("interrogate", s.handle) for s in brief.suspects]
        moves += [("records", s.handle) for s in brief.suspects]
        moves += [("records", p.handle) for p in brief.locations if not p.locked]
        rng.shuffle(moves)
        for kind, handle in moves:
            act = {"search": session.search, "interrogate": session.interrogate}.get(
                kind, session.check_records
            )
            if act(handle).new_facts:
                break
        else:
            break
    raise AssertionError("no suspect was ever revealed")


def test_revealed_exactly_when_the_picker_names_a_locked_suspect():
    """Seed 16 (standard) rules suspects out until a locked one is accusable: that suspect is
    revealed, named as the picker names it, and no other locked suspect is."""
    from gumshoe.api.redact import player_brief

    session = play_until_revealed(16)
    brief = session.brief()
    picker = {c.handle: c.name for c in session.nameable("who").options}
    sent = player_brief(brief).suspects
    for real, shown in zip(brief.suspects, sent, strict=True):
        assert real.revealed == (real.locked and real.handle in picker)
        if real.locked:
            assert shown.description == ""
            assert shown.name == (picker[real.handle] if real.revealed else "")
    assert any(s.revealed for s in sent)


def test_numbers_are_stable_across_an_unlock_and_a_load(store, tmp_path):
    """A card keyed by its number keeps its identity when it flips and after a load."""
    script = Script()
    app = create_app(store, make_service=fake_factory(script, saves_dir=tmp_path / "saves"))
    with TestClient(app) as client:
        before = client.post("/api/games", json={"seed": SEED}).json()
        game = before["game"]
        numbers = {e["handle"]: e["number"] for e in entries(before["brief"])}
        chapel = next(p for p in before["brief"]["locations"] if p["name"] == CHAPEL)
        script.understand(intent="search", target=f"place_{chapel['number']}")
        with client.stream("POST", f"/api/games/{game}/turn", json={"text": "search"}) as r:
            "".join(r.iter_text())
        after = client.get(f"/api/games/{game}").json()["brief"]
        thomas = next(s for s in after["suspects"] if s["name"] == THOMAS)
        assert numbers[thomas["handle"]] == thomas["number"]  # the card that flipped
        assert {e["handle"]: e["number"] for e in entries(after)} == numbers
        saved = client.post(f"/api/games/{game}/save").json()["name"]
        loaded = client.post("/api/games/load", json={"name": saved}).json()["brief"]
    assert [(s["number"], s["name"], s["locked"]) for s in loaded["suspects"]] == [
        (s["number"], s["name"], s["locked"]) for s in after["suspects"]
    ]
