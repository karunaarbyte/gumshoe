import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gumshoe.decider import Recorder
from gumshoe.stats.store import SqliteStatsStore
from tests.stats.factories import choice, make_record, noul


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "stats" / "decisions.db"


@pytest.fixture
def store(db_path):
    return SqliteStatsStore(db_path)


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "decisions.db"
    SqliteStatsStore(path)
    assert path.exists()


def test_reopening_an_existing_database_keeps_its_rows(db_path):
    SqliteStatsStore(db_path).insert([make_record()])
    assert len(SqliteStatsStore(db_path).fetch_calls()) == 1


def test_store_satisfies_the_recorder_protocol(store):
    assert isinstance(store, Recorder)


def test_records_round_trip_exactly(store):
    record = make_record(answers={"intent": choice("action"), "needs": noul(0.7)})
    store.insert([record])
    assert store.fetch_calls() == [record]


def test_failed_call_round_trips_with_null_fields(store):
    record = make_record(
        error="[jev] timed out",
        answers=None,
        input_tokens=None,
        output_tokens=None,
        mean_confidence=None,
        min_confidence=None,
    )
    store.insert([record])
    assert store.fetch_calls() == [record]


def test_booleans_survive_the_integer_columns(store):
    store.insert([make_record(used=False, fallback=True, cold=True)])
    [back] = store.fetch_calls()
    assert (back.used, back.fallback, back.cold) == (False, True, True)


def test_inserting_nothing_is_a_no_op(store):
    store.insert([])
    assert store.fetch_calls() == []


def test_a_failing_batch_is_rolled_back_as_a_whole(store):
    good = make_record(decision_id="good")
    bad = make_record(decision_id="bad", role="neither")  # violates the role CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        store.insert([good, bad])
    assert store.fetch_calls() == []  # the good row did not sneak in


async def test_async_record_writes_through_a_thread(store):
    await store.record([make_record(), make_record(backend="nimble", role="shadow", used=False)])
    assert len(store.fetch_calls()) == 2


async def test_concurrent_writers_do_not_lose_rows(store):
    await asyncio.gather(*(store.record([make_record(decision_id=f"d{i}")]) for i in range(20)))
    assert len(store.fetch_calls()) == 20


def test_filters_by_node(store):
    store.insert([make_record(node="intent"), make_record(node="route", decision_id="d2")])
    assert [r.node for r in store.fetch_calls(node="route")] == ["route"]


def test_calls_come_back_in_time_order(store):
    store.insert(
        [
            make_record(decision_id="late", ts="2026-10-01T12:00:00.000000+00:00"),
            make_record(decision_id="early", ts="2026-10-01T08:00:00.000000+00:00"),
        ]
    )
    assert [r.decision_id for r in store.fetch_calls()] == ["early", "late"]


def test_filters_by_since_and_treats_naive_datetimes_as_utc(store):
    store.insert(
        [
            make_record(decision_id="old", ts="2026-10-01T09:00:00.000000+00:00"),
            make_record(decision_id="new", ts="2026-10-01T11:00:00.000000+00:00"),
        ]
    )
    naive = datetime(2026, 10, 1, 10, 0)
    assert [r.decision_id for r in store.fetch_calls(since=naive)] == ["new"]
    aware = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert [r.decision_id for r in store.fetch_calls(since=aware)] == ["new"]


def test_since_in_another_timezone_is_converted(store):
    store.insert(
        [
            make_record(decision_id="old", ts="2026-10-01T09:00:00.000000+00:00"),
            make_record(decision_id="new", ts="2026-10-01T11:00:00.000000+00:00"),
        ]
    )
    plus_two = timezone(timedelta(hours=2))  # 12:15+02:00 is 10:15 UTC
    assert [
        r.decision_id
        for r in store.fetch_calls(since=datetime(2026, 10, 1, 12, 15, tzinfo=plus_two))
    ] == ["new"]


def test_since_boundary_is_inclusive(store):
    store.insert([make_record(ts="2026-10-01T10:00:00.000000+00:00")])
    assert len(store.fetch_calls(since=datetime(2026, 10, 1, 10, 0, tzinfo=UTC))) == 1


def test_node_parameter_cannot_inject_sql(store, db_path):
    store.insert([make_record()])
    assert store.fetch_calls(node="x' OR '1'='1") == []
    assert store.fetch_calls(node="intent'; DROP TABLE decision_calls; --") == []
    assert len(store.fetch_calls()) == 1  # table still there, row still there
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT count(*) FROM decision_calls").fetchone() == (1,)


def test_fetch_recent_returns_all_calls_of_the_latest_decisions(store):
    for i, minute in enumerate(["01", "02", "03"]):
        ts = f"2026-10-01T10:{minute}:00.000000+00:00"
        store.insert(
            [
                make_record(decision_id=f"d{i}", ts=ts),
                make_record(
                    decision_id=f"d{i}", ts=ts, backend="nimble", role="shadow", used=False
                ),
            ]
        )
    recent = store.fetch_recent(limit=2)
    assert {r.decision_id for r in recent} == {"d1", "d2"}
    assert len(recent) == 4


def test_fetch_recent_respects_the_node_filter(store):
    store.insert(
        [
            make_record(decision_id="a", node="intent"),
            make_record(decision_id="b", node="route"),
        ]
    )
    assert [r.decision_id for r in store.fetch_recent(limit=10, node="route")] == ["b"]


def test_fetch_recent_cannot_be_injected_either(store):
    store.insert([make_record()])
    assert store.fetch_recent(limit=5, node="x' OR '1'='1") == []


def test_empty_store_returns_empty_lists(store):
    assert store.fetch_calls() == []
    assert store.fetch_recent(limit=5) == []


def test_fetch_recent_breaks_timestamp_ties_by_insertion_order(store):
    same = "2026-10-01T10:00:00.000000+00:00"
    store.insert([make_record(decision_id="first", ts=same)])
    store.insert([make_record(decision_id="second", ts=same)])
    assert [r.decision_id for r in store.fetch_recent(limit=1)] == ["second"]


def test_timestamps_are_normalised_to_utc_microseconds_on_insert(store):
    store.insert(
        [
            make_record(decision_id="offset", ts="2026-10-01T12:00:00+02:00"),
            make_record(decision_id="plain", ts="2026-10-01T09:00:00+00:00"),
        ]
    )
    stored = {r.decision_id: r.ts for r in store.fetch_calls()}
    assert stored == {
        "offset": "2026-10-01T10:00:00.000000+00:00",
        "plain": "2026-10-01T09:00:00.000000+00:00",
    }
    since = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)  # between the two once both are UTC
    assert [r.decision_id for r in store.fetch_calls(since=since)] == ["offset"]


def test_a_malformed_timestamp_is_rejected_before_anything_is_written(store):
    with pytest.raises(ValueError):
        store.insert(
            [make_record(decision_id="ok"), make_record(decision_id="bad", ts="yesterday")]
        )
    assert store.fetch_calls() == []
