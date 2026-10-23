import sqlite3
from concurrent.futures import ThreadPoolExecutor

from gumshoe.decider import UsageLedger
from gumshoe.stats import SqliteStatsStore
from gumshoe.stats.store import SCHEMA


def test_it_is_a_ledger(tmp_path):
    assert isinstance(SqliteStatsStore(tmp_path / "d.db"), UsageLedger)


def test_usage_adds_up_per_day_and_key(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    store.add_usage("2026-10-16", "1.1.1.1", 100)
    store.add_usage("2026-10-16", "1.1.1.1", 50)
    store.add_usage("2026-10-16", "2.2.2.2", 7)
    store.add_usage("2026-10-17", "1.1.1.1", 9)
    assert store.usage_totals("2026-10-16") == {"1.1.1.1": 150, "2.2.2.2": 7}
    assert store.usage_totals("2026-10-17") == {"1.1.1.1": 9}
    assert store.usage_totals("2026-10-18") == {}


def test_the_totals_survive_reopening_the_database(tmp_path):
    SqliteStatsStore(tmp_path / "d.db").add_usage("2026-10-16", "", 5)
    assert SqliteStatsStore(tmp_path / "d.db").usage_totals("2026-10-16") == {"": 5}


def test_an_old_database_without_the_table_gets_it(tmp_path):
    path = tmp_path / "old.db"
    old_schema = SCHEMA.split("CREATE TABLE IF NOT EXISTS jev_usage")[0]  # before this plan
    with sqlite3.connect(path) as conn:
        conn.executescript(old_schema)
        conn.execute(
            "INSERT INTO decision_calls (decision_id, node, backend, role, used, fallback, cold,"
            " ts, latency_ms, state_preview) VALUES ('d', 'n', 'b', 'primary', 1, 0, 0,"
            " '2026-10-16T00:00:00+00:00', 1.0, 'p')"
        )
    conn.close()
    store = SqliteStatsStore(path)  # opening adds the usage table and leaves the rest alone
    store.add_usage("2026-10-16", "k", 1)
    assert store.usage_totals("2026-10-16") == {"k": 1}
    assert len(store.fetch_decisions(["d"])) == 1


def test_purge_usage_removes_old_days_only(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    for day in ("2026-09-01", "2026-10-01", "2026-10-16"):
        store.add_usage(day, "k", 1)
    assert store.purge_usage("2026-10-01") == 1
    assert store.usage_totals("2026-09-01") == {} and store.usage_totals("2026-10-01") == {"k": 1}


def test_concurrent_adds_from_threads_lose_nothing(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.add_usage("2026-10-16", "k", 3), range(200)))
    assert store.usage_totals("2026-10-16") == {"k": 600}


def test_hostile_keys_are_data_not_sql(tmp_path):
    store = SqliteStatsStore(tmp_path / "d.db")
    key = "x'); DROP TABLE jev_usage; --"
    store.add_usage("2026-10-16", key, 2)
    assert store.usage_totals("2026-10-16") == {key: 2}
