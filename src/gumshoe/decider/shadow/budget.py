"""Counting Jev spend: input tokens per UTC day, per client key and in total.

Reads of the meter never do I/O: memory is the source, and it is authoritative for the running
process. The ledger is read once, by `UsageMeter.load()` at startup, so a restart resumes the
day; every count is written through to it in a worker thread. The ledger is best effort: a
failing or slow ledger (SQLite can block for its busy timeout and raise) is logged by exception
type and never fails or delays a decision. A ledger outage at startup means that day's count
starts at 0, and a day entered at midnight starts empty without a read (this process is the
only writer); the cap built on this meter is approximate by design.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.models import DecisionResult, Question
from gumshoe.decider.contract.usage import UsageLedger, client_key, estimate_tokens

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UsageMeter:
    """Input tokens spent today, per client key and in total (see the module docstring)."""

    def __init__(
        self, ledger: UsageLedger | None, *, now: Callable[[], datetime] = _utc_now
    ) -> None:
        self._ledger = ledger
        self._now = now
        self._day = ""
        self._by_key: dict[str, int] = {}
        self._loaded = False
        self._writes: set[asyncio.Task[None]] = set()

    def day(self) -> str:
        """Today's UTC date as YYYY-MM-DD (isoformat always pads the year to four digits)."""
        return self._now().astimezone(UTC).date().isoformat()

    async def load(self) -> None:
        """Resume today from the ledger, off the event loop. Await it once before serving;
        later calls do nothing. A failing ledger is logged and leaves today's count at 0."""
        if self._loaded or self._ledger is None:
            self._loaded = True
            return
        self._loaded = True
        if self._by_key:  # counted before startup's load: the wiring awaited it too late
            logger.warning("usage meter loaded after counting began")
        day = self.day()
        try:
            stored = await asyncio.to_thread(self._ledger.usage_totals, day)
        except Exception as exc:  # the budget must hold without the database
            logger.warning("usage ledger read failed: %s", type(exc).__name__)
            return
        self._roll()
        if self._day != day:  # midnight passed while loading: the old day no longer matters
            return
        # anything counted while the read ran may or may not be in it: never count it twice
        for key, tokens in stored.items():
            self._by_key[key] = max(self._by_key.get(key, 0), int(tokens))

    def _roll(self) -> None:
        """Enter today. A new day starts empty, with no read."""
        day = self.day()
        if day != self._day:
            self._day, self._by_key = day, {}

    def total(self) -> int:
        self._roll()
        return sum(self._by_key.values())

    def tokens(self, key: str) -> int:
        self._roll()
        return self._by_key.get(key, 0)

    def _count(self, key: str, tokens: int) -> tuple[str, int]:
        self._roll()
        tokens = max(1, int(tokens))  # every call counts, and the ledger never sees zero or less
        self._by_key[key] = self._by_key.get(key, 0) + tokens
        return self._day, tokens

    async def _write(self, day: str, key: str, tokens: int) -> None:
        if self._ledger is None:
            return
        try:
            await asyncio.to_thread(self._ledger.add_usage, day, key, tokens)
        except Exception as exc:  # memory already counted it; the ledger is best effort
            logger.warning("usage ledger write failed: %s", type(exc).__name__)

    async def add(self, key: str, tokens: int) -> None:
        """Count `tokens` for `key` today, waiting for the ledger write."""
        day, tokens = self._count(key, tokens)
        await self._write(day, key, tokens)

    def note(self, key: str, tokens: int) -> None:
        """Count `tokens` for `key` today in memory now, with no await; write the ledger in the
        background so a decision is never held up by the database. Needs a running loop."""
        day, tokens = self._count(key, tokens)
        if self._ledger is not None:
            task = asyncio.create_task(self._write(day, key, tokens))
            self._writes.add(task)
            task.add_done_callback(self._writes.discard)

    async def flush(self, grace_s: float | None = 5.0) -> None:
        """Wait up to `grace_s` seconds for background ledger writes; give up on the rest (their
        tokens stay counted in memory, only the ledger misses them)."""
        pending = set(self._writes)
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=grace_s)
        if still_running:
            logger.warning("usage ledger writes still pending at close: %d", len(still_running))
            for task in still_running:
                task.cancel()  # stops waiting; a write already in its thread may still land
            await asyncio.gather(*still_running, return_exceptions=True)


class MeteredDecider:
    """Counts what each call to `inner` (the Jev client) costs in input tokens."""

    def __init__(
        self, inner: Decider, meter: UsageMeter, *, flush_grace_s: float | None = 5.0
    ) -> None:
        self.name = inner.name
        self._inner = inner
        self._meter = meter
        self._flush_grace_s = flush_grace_s  # how long aclose waits for ledger writes

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
        except BaseException:
            # a failed call (a bug in the client counts too) or a cancelled one (a turn that hit
            # its time limit) may still have been billed: count what we sent, roughly. `note`
            # does not await, so even a cancellation is counted before it propagates.
            self._meter.note(key, estimate_tokens(state, questions))
            raise
        tokens = result.usage.input_tokens if result.usage else estimate_tokens(state, questions)
        self._meter.note(key, tokens)
        return result

    async def aclose(self) -> None:
        try:
            await self._meter.flush(self._flush_grace_s)
        finally:
            await self._inner.aclose()


class BudgetDecider:
    """Jev while today's budget lasts, Nimble alone after. `normal` is the usual decider (Jev
    primary, Nimble shadow); `fallback` is Nimble alone. A client over its own share is moved to
    the fallback without affecting anyone else.

    Each call is routed once, from memory, before its first await: a call already on Jev runs
    to the end even if the cap is reached meanwhile. A fallback failure raises as usual."""

    def __init__(
        self,
        normal: Decider,
        fallback: Decider,
        meter: UsageMeter,
        *,
        daily_tokens: int,
        ip_tokens: int,
    ) -> None:
        self.name = normal.name
        self._normal = normal
        self._fallback = fallback
        self._meter = meter
        self._daily = daily_tokens  # 0 means unlimited
        self._ip = ip_tokens  # 0 means unlimited

    @property
    def shadow_skipped(self) -> int:
        """Shadow calls the normal decider skipped (for the admin report)."""
        return int(getattr(self._normal, "shadow_skipped", 0))

    @property
    def mode(self) -> Literal["normal", "slow"]:
        return "slow" if self._daily > 0 and self._meter.total() >= self._daily else "normal"

    def _choose(self) -> Decider:
        if self.mode == "slow":
            return self._fallback
        key = client_key.get()
        if key and self._ip > 0 and self._meter.tokens(key) >= self._ip:
            return self._fallback
        return self._normal

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        return await self._choose().decide(state, questions, node=node, decision_id=decision_id)

    async def drain(self, grace_s: float | None = None) -> None:
        try:
            await self._drain(self._normal, grace_s)
        finally:
            await self._drain(self._fallback, grace_s)

    async def load(self) -> None:
        """Resume today's count from the ledger. Await it once at startup, before serving."""
        await self._meter.load()

    @staticmethod
    async def _drain(inner: Decider, grace_s: float | None) -> None:
        drain = getattr(inner, "drain", None)
        if drain is not None:
            await drain(grace_s)

    async def aclose(self) -> None:
        try:
            await self._normal.aclose()
        finally:
            await self._fallback.aclose()
