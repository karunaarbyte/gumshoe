"""SQLite persistence for decision call records."""

import asyncio
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import TypeAdapter

from gumshoe.decider import Answer, CallRecord

ANSWERS = TypeAdapter(dict[str, Answer])

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


def to_utc_iso(moment: datetime) -> str:
    """Same fixed format the recorder writes, so string comparison orders by time."""
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return moment.isoformat(timespec="microseconds")


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

    def fetch_calls(
        self, *, node: str | None = None, since: datetime | None = None
    ) -> list[CallRecord]:
        """Calls in time order. A naive `since` is read as UTC, like every timestamp we store."""
        sql = "SELECT * FROM decision_calls WHERE 1 = 1"
        params: list[Any] = []
        if node is not None:
            sql += " AND node = ?"
            params.append(node)
        if since is not None:
            sql += " AND ts >= ?"
            params.append(to_utc_iso(since))
        return self._query(sql + " ORDER BY ts, id", params)

    def fetch_recent(self, *, limit: int, node: str | None = None) -> list[CallRecord]:
        """All calls of the `limit` most recent decisions."""
        where, params = ("WHERE node = ?", [node]) if node is not None else ("", [])
        with closing(self._connect()) as conn:
            ids = [
                row["decision_id"]
                for row in conn.execute(
                    f"SELECT decision_id FROM decision_calls {where} "
                    "GROUP BY decision_id ORDER BY MAX(ts) DESC, MAX(id) DESC LIMIT ?",
                    [*params, limit],
                )
            ]
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        return self._query(
            f"SELECT * FROM decision_calls WHERE decision_id IN ({marks}) ORDER BY ts, id", ids
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
            error=row["error"],
            state_preview=row["state_preview"],
            answers=ANSWERS.validate_json(row["answers_json"]) if row["answers_json"] else None,
        )
