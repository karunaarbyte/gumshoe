"""SQLite persistence for decision call records."""

import asyncio
import logging
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import TypeAdapter, ValidationError

from gumshoe.decider import Answer, CallRecord
from gumshoe.stats.timeutil import to_utc_iso

logger = logging.getLogger(__name__)

ANSWERS = TypeAdapter(dict[str, Answer])
# The error a row gets when its stored answers no longer parse (say a NaN written before the
# contract refused it): the row still loads, so one bad row never takes the stats down.
UNREADABLE_ANSWERS = "the stored answers could not be read"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT    NOT NULL,
    node            TEXT    NOT NULL,
    backend         TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK (role IN ('primary', 'shadow')),
    used            INTEGER NOT NULL,
    fallback        INTEGER NOT NULL,
    cold            INTEGER NOT NULL,
    ts              TEXT    NOT NULL,
    latency_ms      REAL    NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    mean_confidence REAL,
    min_confidence  REAL,
    error           TEXT,
    state_preview   TEXT    NOT NULL,
    answers_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_node_ts ON decision_calls (node, ts);
CREATE INDEX IF NOT EXISTS idx_calls_decision ON decision_calls (decision_id);
CREATE TABLE IF NOT EXISTS jev_usage (
    day    TEXT    NOT NULL,
    key    TEXT    NOT NULL,
    tokens INTEGER NOT NULL,
    PRIMARY KEY (day, key)
);
"""

COLUMNS = (
    "decision_id",
    "node",
    "backend",
    "role",
    "used",
    "fallback",
    "cold",
    "ts",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "mean_confidence",
    "min_confidence",
    "error",
    "state_preview",
    "answers_json",
)
INSERT = (
    f"INSERT INTO decision_calls ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})"
)


class SqliteStatsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    async def record(self, records: Sequence[CallRecord]) -> None:
        await asyncio.to_thread(self.insert, list(records))

    def insert(self, records: Sequence[CallRecord]) -> None:
        rows = [self._to_row(r) for r in records]
        with closing(self._connect()) as conn, conn:  # `with conn` = one transaction
            conn.executemany(INSERT, rows)

    def add_usage(self, day: str, key: str, tokens: int) -> None:
        """Add to a day's token count for a key. One upsert statement, so concurrent adds queue
        on SQLite's write lock and none is lost."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO jev_usage (day, key, tokens) VALUES (?, ?, ?) "
                "ON CONFLICT (day, key) DO UPDATE SET tokens = tokens + excluded.tokens",
                (day, key, tokens),
            )

    def usage_totals(self, day: str) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT key, tokens FROM jev_usage WHERE day = ?", (day,))
            return {row["key"]: row["tokens"] for row in rows}

    def purge_usage(self, before_day: str) -> int:
        """Delete the days earlier than `before_day`; returns how many rows went."""
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM jev_usage WHERE day < ?", (before_day,)).rowcount

    def purge_decisions(self, older_than: datetime) -> int:
        """Delete every decision whose first call is older than `older_than`, all its rows
        (primary and shadow) together. Returns how many decisions went. A naive `older_than` is
        read as UTC. One transaction, so a reader sees a decision whole or not at all; the ids
        go in chunks to stay under SQLite's variable limit. Not batched across transactions: at
        this store's size one delete is brief, and batching would only add complexity."""
        cutoff = to_utc_iso(older_than)
        with closing(self._connect()) as conn, conn:
            # The write lock first: a read then upgraded to a write can fail with SQLITE_BUSY.
            conn.execute("BEGIN IMMEDIATE")
            ids = [
                row["decision_id"]
                for row in conn.execute(
                    "SELECT decision_id FROM decision_calls GROUP BY decision_id "
                    "HAVING MIN(ts) < ?",
                    (cutoff,),
                )
            ]
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ", ".join("?" for _ in chunk)
                conn.execute(f"DELETE FROM decision_calls WHERE decision_id IN ({marks})", chunk)
            return len(ids)

    def fetch_calls(
        self, *, node: str | None = None, since: datetime | None = None
    ) -> list[CallRecord]:
        """Calls in time order, for the decisions that started at or after `since`.

        A naive `since` is read as UTC, like every timestamp we store. Everything is loaded into
        memory for aggregation, which is fine for tens of thousands of rows, not millions.
        """
        sql = "SELECT * FROM decision_calls WHERE 1 = 1"
        params: list[Any] = []
        if node is not None:
            sql += " AND node = ?"
            params.append(node)
        if since is not None:
            # By decision, not by row: a decision belongs to the window if its first call does,
            # so its primary and shadow rows are never split by the cutoff.
            sql += (
                " AND decision_id IN (SELECT decision_id FROM decision_calls"
                " GROUP BY decision_id HAVING MIN(ts) >= ?)"
            )
            params.append(to_utc_iso(since))
        return self._query(sql + " ORDER BY ts, id", params)

    def fetch_recent(
        self, *, limit: int, node: str | None = None, since: datetime | None = None
    ) -> list[CallRecord]:
        """All calls of the `limit` most recently *started* decisions (those that started at or
        after `since`, when given), so the work is bounded by `limit`, not by the table."""
        where, params = ("WHERE node = ?", [node]) if node is not None else ("", [])
        having = ""
        if since is not None:
            having = "HAVING MIN(ts) >= ?"
            params = [*params, to_utc_iso(since)]
        with closing(self._connect()) as conn:
            ids = [
                row["decision_id"]
                for row in conn.execute(
                    f"SELECT decision_id FROM decision_calls {where} "
                    f"GROUP BY decision_id {having} ORDER BY MIN(ts) DESC, MIN(id) DESC LIMIT ?",
                    [*params, limit],
                )
            ]
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        return self._query(
            f"SELECT * FROM decision_calls WHERE decision_id IN ({marks}) ORDER BY ts, id", ids
        )

    def fetch_decisions(self, decision_ids: Sequence[str]) -> list[CallRecord]:
        """Every call of the given decisions, in time order. An id with no row yet (a primary's
        record is written in the background) simply has no calls."""
        if not decision_ids:
            return []
        marks = ", ".join("?" for _ in decision_ids)
        return self._query(
            f"SELECT * FROM decision_calls WHERE decision_id IN ({marks}) ORDER BY ts, id",
            list(decision_ids),
        )

    # -- row <-> record --------------------------------------------------------------------

    def _query(self, sql: str, params: Sequence[Any]) -> list[CallRecord]:
        with closing(self._connect()) as conn:
            return [self._from_row(row) for row in conn.execute(sql, params)]

    @staticmethod
    def _to_row(r: CallRecord) -> tuple[Any, ...]:
        answers_json = ANSWERS.dump_json(r.answers).decode() if r.answers is not None else None
        return (
            r.decision_id,
            r.node,
            r.backend,
            r.role,
            int(r.used),
            int(r.fallback),
            int(r.cold),
            to_utc_iso(
                datetime.fromisoformat(r.ts)
            ),  # one fixed format keeps text order = time order
            r.latency_ms,
            r.input_tokens,
            r.output_tokens,
            r.mean_confidence,
            r.min_confidence,
            r.error,
            r.state_preview,
            answers_json,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CallRecord:
        answers: dict[str, Answer] | None = None
        error: str | None = row["error"]
        if row["answers_json"]:
            try:
                answers = ANSWERS.validate_json(row["answers_json"])
            except ValidationError:
                logger.warning("decision_calls row %s holds answers that do not parse", row["id"])
                error = error or UNREADABLE_ANSWERS
        return CallRecord(
            decision_id=row["decision_id"],
            node=row["node"],
            backend=row["backend"],
            role=cast(Literal["primary", "shadow"], row["role"]),
            used=bool(row["used"]),
            fallback=bool(row["fallback"]),
            cold=bool(row["cold"]),
            ts=row["ts"],
            latency_ms=row["latency_ms"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            mean_confidence=row["mean_confidence"],
            min_confidence=row["min_confidence"],
            error=error,
            state_preview=row["state_preview"],
            answers=answers,
        )
