import httpx
import pytest

from gumshoe.api import create_app
from gumshoe.config import Settings
from gumshoe.decider import CallRecord
from gumshoe.stats import SqliteStatsStore
from tests.agent.fakes import Script
from tests.api.client import TestClient
from tests.api.helpers import fake_factory
from tests.stats.factories import choice

NOTHING = "no such decision"
NOT_FOUND = {"code": "not_found", "message": NOTHING}
# a well-formed decision id (uuid4().hex) that this game never made
FOREIGN = "0123456789abcdef0123456789abcdef"
INTERNAL = {"code": "internal", "message": "something went wrong"}
LOCKED = "Vesna Okonkwo-Lindqvist"  # a locked suspect's name, as the hidden state would hold it


@pytest.fixture
def store(tmp_path):
    return SqliteStatsStore(tmp_path / "decisions.db")


def record(decision_id, node="understand", preview="private typed words", **changes):
    fields = dict(
        decision_id=decision_id,
        node=node,
        backend="jev",
        role="primary",
        used=True,
        fallback=False,
        cold=False,
        ts="2026-10-16T10:00:00.000000+00:00",
        latency_ms=300.0,
        input_tokens=10,
        output_tokens=2,
        mean_confidence=0.9,
        min_confidence=0.9,
        error=None,
        state_preview=preview,
        answers={},
    )
    fields.update(changes)
    return CallRecord(**fields)


def decision_ids_of(client, game):
    turns = client.get(f"/api/games/{game}/turns").json()
    return [e["decision_id"] for t in turns for e in t["events"] if e.get("decision_id")]


def play(client):
    game = client.post("/api/games", json={"seed": 1}).json()["game"]
    with client.stream("POST", f"/api/games/{game}/turn", json={"text": "notebook"}) as r:
        r.read()
    ids = decision_ids_of(client, game)
    assert ids, "the scripted turn should produce a decision id"
    return game, ids[0]


def played(store, *, settings=None, raise_server_exceptions=True, turns=1):
    """An app and a game with one turn whose intent event carries a decision id. `turns` scripts
    that many understand calls, for more games."""
    script = Script()
    for _ in range(turns):
        script = script.understand(intent="notebook")
    app = create_app(store, make_service=fake_factory(script), settings=settings)
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    client.__enter__()
    game, decision = play(client)
    return client, game, decision


def test_the_owner_reads_the_redacted_decision(store):
    client, game, decision = played(store)
    try:
        store.insert([record(decision)])
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        assert r.status_code == 200
        body = r.json()
        assert body["decision_id"] == decision and body["state_preview"] == ""
        assert "private typed words" not in r.text
        assert "set-cookie" not in r.headers  # the owner is read, never issued
    finally:
        client.__exit__(None, None, None)


def test_a_decision_not_yet_recorded_says_so(store):
    client, game, decision = played(store)
    try:
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        assert (r.status_code, r.json()["code"]) == (404, "not_recorded_yet")
    finally:
        client.__exit__(None, None, None)


def test_an_id_that_is_not_in_this_games_transcript_is_refused_even_if_it_exists(store):
    client, game, decision = played(store)
    try:
        store.insert([record("someone-elses-decision")])
        r = client.get(f"/api/games/{game}/decisions/someone-elses-decision")
        assert (r.status_code, r.json()) == (404, {"code": "not_found", "message": NOTHING})
    finally:
        client.__exit__(None, None, None)


def test_a_well_formed_id_in_the_store_but_not_this_transcript_reads_like_no_id_at_all(store):
    client, game, decision = played(store)
    try:
        store.insert([record(FOREIGN)])
        stored = client.get(f"/api/games/{game}/decisions/{FOREIGN}")
        absent = client.get(f"/api/games/{game}/decisions/{'f' * 32}")
        assert (stored.status_code, stored.json()) == (404, NOT_FOUND)
        assert stored.content == absent.content
    finally:
        client.__exit__(None, None, None)


def test_a_decision_from_my_other_game_is_not_served_through_this_one(store):
    client, game, decision = played(store, turns=2)
    try:
        other, theirs = play(client)
        store.insert([record(decision), record(theirs)])
        assert theirs != decision
        r = client.get(f"/api/games/{game}/decisions/{theirs}")
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert client.get(f"/api/games/{other}/decisions/{theirs}").status_code == 200
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        "0123456789ABCDEF0123456789ABCDEF",  # upper case
        "0123456789abcdef0123456789abcde",  # 31
        "0123456789abcdef0123456789abcdef0",  # 33
        pytest.param("a" * 5000, id="5000-chars"),
        "%20" + "a" * 32,
        "g" * 32,  # not hex
    ],
)
def test_a_malformed_id_is_the_same_plain_404_and_reaches_no_lookup(store, monkeypatch, bad):
    client, game, decision = played(store)
    try:
        looked: list[object] = []
        monkeypatch.setattr(store, "fetch_decisions", lambda ids: looked.append(ids) or [])
        r = client.get(f"/api/games/{game}/decisions/{bad}")
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert looked == []
    finally:
        client.__exit__(None, None, None)


def test_another_session_cannot_read_it_and_gets_the_missing_game_answer(store):
    client, game, decision = played(store)
    try:
        store.insert([record(decision)])
        mine = client.cookies
        client.cookies = httpx.Cookies()
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        client.cookies = mine
        assert (r.status_code, r.json()["code"]) == (404, "unknown_game")
    finally:
        client.__exit__(None, None, None)


def test_a_stranger_a_missing_game_and_no_session_all_read_exactly_like_a_strangers_game(store):
    client, game, decision = played(store)
    try:
        store.insert([record(decision)])
        mine = client.cookies
        client.cookies = type(mine)()
        no_session = client.get(f"/api/games/{game}/decisions/{decision}")
        malformed_no_session = client.get(f"/api/games/{game}/decisions/nope")
        client.post("/api/games", json={"seed": 99})  # a stranger with a game of their own
        stranger = client.get(f"/api/games/{game}/decisions/{decision}")
        malformed = client.get(f"/api/games/{game}/decisions/nope")
        reference = client.get(f"/api/games/{game}")
        client.cookies = mine
        missing = client.get(f"/api/games/{'0' * 16}/decisions/{decision}")
        assert reference.status_code == 404
        for r in (no_session, malformed_no_session, stranger, malformed, missing):
            assert (r.status_code, r.content) == (404, reference.content)
            assert "set-cookie" not in r.headers
    finally:
        client.__exit__(None, None, None)


def test_the_accusation_options_are_not_shown(store):
    client, game, decision = played(store)
    try:
        store.insert([record(decision, node="parse_accusation")])
        body = client.get(f"/api/games/{game}/decisions/{decision}").json()
        assert all(call["answers"] == {} for call in body["calls"])
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("node", ["understand", "parse_accusation"])
def test_no_locked_name_in_the_stored_decision_reaches_the_body(store, node):
    client, game, decision = played(store)
    try:
        store.insert(
            [
                record(
                    decision,
                    node=node,
                    preview=f"hidden: {LOCKED} was at the docks",
                    answers={"intent": choice(LOCKED), f"is {LOCKED} lying": choice("yes")},
                ),
                record(
                    decision,
                    node=node,
                    backend="nimble",
                    role="shadow",
                    used=False,
                    error=f"ValueError: unexpected option {LOCKED!r}",
                    answers=None,
                ),
            ]
        )
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        assert r.status_code == 200
        assert len(r.json()["calls"]) == 2
        for piece in (LOCKED, "Vesna", "Okonkwo", "docks", "lying"):
            assert piece not in r.text
    finally:
        client.__exit__(None, None, None)


def test_a_store_failure_is_a_generic_500(store, monkeypatch):
    client, game, decision = played(store, raise_server_exceptions=False)
    try:

        def broken(ids):
            raise RuntimeError(f"database is locked at /secret/path {LOCKED}")

        monkeypatch.setattr(store, "fetch_decisions", broken)
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        assert (r.status_code, r.json()) == (500, INTERNAL)
        assert "secret" not in r.text and LOCKED not in r.text
    finally:
        client.__exit__(None, None, None)


def test_the_request_rate_limit_counts_it_like_any_other_get(store):
    # the game, its turn and the transcript read take three of the four requests a minute
    settings = Settings(_env_file=None, ip_requests_per_minute=4)
    client, game, decision = played(store, settings=settings)
    try:
        store.insert([record(decision)])
        assert client.get(f"/api/games/{game}/decisions/{decision}").status_code == 200
        r = client.get(f"/api/games/{game}/decisions/{decision}")
        assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
    finally:
        client.__exit__(None, None, None)
