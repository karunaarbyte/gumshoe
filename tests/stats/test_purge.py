import sqlite3
from datetime import UTC, datetime

from gumshoe.stats import SqliteStatsStore
from tests.stats.factories import make_record


def rec(decision_id: str, role: str, ts: str):
    return make_record(
        decision_id=decision_id,
        role=role,
        backend="jev" if role == "primary" else "nimble",
        used=role == "primary",
        ts=ts,
    )


CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def row_count(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM decision_calls").fetchone()[0]
    finally:
        conn.close()


def test_purge_removes_whole_old_decisions_and_keeps_newer_ones(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert(
        [
            rec("old", "primary", "2026-08-01T00:00:00.000000+00:00"),
            rec("old", "shadow", "2026-08-01T00:00:01.000000+00:00"),
            rec("new", "primary", "2026-10-10T00:00:00.000000+00:00"),
            rec("new", "shadow", "2026-10-10T00:00:01.000000+00:00"),
        ]
    )
    assert store.purge_decisions(CUTOFF) == 1
    assert store.fetch_decisions(["old"]) == []
    assert len(store.fetch_decisions(["new"])) == 2
    assert row_count(tmp_path / "d.db") == 2  # no orphan rows


def test_a_decision_is_judged_by_its_first_call_and_removed_whole(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert(
        [
            rec("edge", "primary", "2026-08-31T23:59:59.000000+00:00"),
            rec("edge", "shadow", "2026-09-01T00:00:05.000000+00:00"),
        ]
    )
    assert store.purge_decisions(CUTOFF) == 1
    assert store.fetch_decisions(["edge"]) == []
    assert row_count(tmp_path / "d.db") == 0


def test_a_decision_whose_first_call_is_new_is_kept_whole(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert(
        [
            rec("fresh", "primary", "2026-09-01T00:00:00.000000+00:00"),
            rec("fresh", "shadow", "2026-09-01T00:00:01.000000+00:00"),
        ]
    )
    assert store.purge_decisions(CUTOFF) == 0  # exactly at the cutoff is not older
    assert len(store.fetch_decisions(["fresh"])) == 2


def test_the_cutoff_is_compared_in_utc_whatever_zone_it_is_given_in(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert([rec("a", "primary", "2026-08-31T23:00:00.000000+00:00")])
    from datetime import timedelta, timezone

    plus_five = timezone(timedelta(hours=5))
    # 2026-09-01 04:00 +05:00 is 2026-08-31 23:00 UTC: not older than the call
    assert store.purge_decisions(datetime(2026, 9, 1, 4, tzinfo=plus_five)) == 0
    assert store.purge_decisions(datetime(2026, 9, 1, 4, 0, 1, tzinfo=plus_five)) == 1
    # a naive cutoff is read as UTC
    store.insert([rec("b", "primary", "2026-08-01T00:00:00.000000+00:00")])
    assert store.purge_decisions(datetime(2026, 9, 1)) == 1


def test_purging_an_empty_store_is_fine(tmp_path):
    assert SqliteStatsStore(tmp_path / "d.db").purge_decisions(CUTOFF) == 0


def test_purge_takes_the_write_lock_before_it_reads(tmp_path, monkeypatch):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.insert([rec("old", "primary", "2026-08-01T00:00:00.000000+00:00")])
    statements: list[str] = []
    connect = store._connect

    def traced():
        conn = connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(store, "_connect", traced)
    assert store.purge_decisions(CUTOFF) == 1
    # a deferred read upgraded to a write can fail with SQLITE_BUSY: lock first, then read
    assert statements[0] == "BEGIN IMMEDIATE"
    assert statements[1].startswith("SELECT decision_id")
