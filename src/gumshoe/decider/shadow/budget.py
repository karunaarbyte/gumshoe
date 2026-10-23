"""Counting Jev spend and switching to Nimble alone when a daily cap is reached."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.models import DecisionResult, Question
from gumshoe.decider.contract.usage import UsageLedger, client_key, estimate_tokens

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UsageMeter:
    """Input tokens spent today, per client key and in total.

    Memory is the source for reads and is authoritative for the running process: each add
    updates memory first and only then writes through to the ledger (in a worker thread), so a
    restart resumes the day. The ledger is best effort: a failing or slow ledger (SQLite can
    block for its busy timeout and raise) is logged by exception type and never stops counting.
    """

    def __init__(
        self, ledger: UsageLedger | None, *, now: Callable[[], datetime] = _utc_now
    ) -> None:
        self._ledger = ledger
        self._now = now
        self._day = ""
        self._by_key: dict[str, int] = {}
        self._writes: set[asyncio.Task[None]] = set()

    def day(self) -> str:
        """Today's UTC date as YYYY-MM-DD (isoformat always pads the year to four digits)."""
        return self._now().astimezone(UTC).date().isoformat()

    def _load(self, day: str) -> dict[str, int]:
        if self._ledger is None:
            return {}
        try:
            return dict(self._ledger.usage_totals(day))
        except Exception as exc:  # the budget must hold without the database
            logger.warning("usage ledger read failed: %s", type(exc).__name__)
            return {}

    def _roll(self) -> None:
        """Enter today from a synchronous read (total/tokens). Loads the ledger once a day."""
        day = self.day()
        if day != self._day:
            self._day, self._by_key = day, self._load(day)

    async def _roll_async(self) -> str:
        """Enter today without blocking the event loop; returns the day entered."""
        day = self.day()
        if day != self._day:
            loaded = await asyncio.to_thread(self._load, day)
            # another add (or a sync read) may have entered the day while this one loaded; its
            # load came first and memory may already hold this process's counts, so keep it
            if day != self._day:
                self._day, self._by_key = day, loaded
        return day

    def total(self) -> int:
        self._roll()
        return sum(self._by_key.values())

    def tokens(self, key: str) -> int:
        self._roll()
        return self._by_key.get(key, 0)

    async def _count(self, key: str, tokens: int) -> tuple[str, int]:
        day = await self._roll_async()
        tokens = max(1, int(tokens))  # every call counts, and the ledger never sees zero or less
        if day == self._day:  # (a day that rolled on during the load counts in no memory)
            self._by_key[key] = self._by_key.get(key, 0) + tokens
        return day, tokens

    async def _write(self, day: str, key: str, tokens: int) -> None:
        if self._ledger is None:
            return
        try:
            await asyncio.to_thread(self._ledger.add_usage, day, key, tokens)
        except Exception as exc:  # memory already counted it; the ledger is best effort
            logger.warning("usage ledger write failed: %s", type(exc).__name__)

    async def add(self, key: str, tokens: int) -> None:
        """Count `tokens` for `key` today, waiting for the ledger write."""
        day, tokens = await self._count(key, tokens)
        await self._write(day, key, tokens)

    async def count(self, key: str, tokens: int) -> None:
        """Count `tokens` for `key` today in memory now; write the ledger in the background,
        so a decision is never held up by the database. `flush` waits for those writes."""
        day, tokens = await self._count(key, tokens)
        if self._ledger is not None:
            task = asyncio.create_task(self._write(day, key, tokens))
            self._writes.add(task)
            task.add_done_callback(self._writes.discard)

    async def flush(self) -> None:
        """Wait for every background ledger write started so far."""
        while self._writes:
            await asyncio.gather(*self._writes)


class MeteredDecider:
    """Counts what each call to `inner` (the Jev client) costs in input tokens."""

    def __init__(self, inner: Decider, meter: UsageMeter) -> None:
        self.name = inner.name
        self._inner = inner
        self._meter = meter

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        key = client_key.get()
        try:
            result = await self._inner.decide(state, questions, node=node, decision_id=decision_id)
        except Exception:
            # a failed call (a bug in the client counts too) may still have been billed: count
            # what we sent, roughly. A cancellation is a BaseException and counts nothing.
            await self._meter.count(key, estimate_tokens(state, questions))
            raise
        tokens = result.usage.input_tokens if result.usage else estimate_tokens(state, questions)
        await self._meter.count(key, tokens)
        return result

    async def aclose(self) -> None:
        try:
            await self._meter.flush()
        finally:
            await self._inner.aclose()
