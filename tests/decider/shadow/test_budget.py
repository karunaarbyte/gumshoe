import asyncio
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gumshoe.decider import client_key, estimate_tokens
from gumshoe.decider.contract.errors import DeciderError
from gumshoe.decider.contract.models import DecisionResult, Usage
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.decider.shadow.budget import MeteredDecider, UsageMeter
from tests.decider.fakes import FakeDecider


class MemoryLedger:
    def __init__(self):
        self.rows: dict[tuple[str, str], int] = {}

    def add_usage(self, day, key, tokens):
        self.rows[(day, key)] = self.rows.get((day, key), 0) + tokens

    def usage_totals(self, day):
        return {k: v for (d, k), v in self.rows.items() if d == day}


class SpyLedger(MemoryLedger):
    """A MemoryLedger that counts reads, to prove when the meter does (not) touch storage."""

    def __init__(self):
        super().__init__()
        self.reads: list[str] = []

    def usage_totals(self, day):
        self.reads.append(day)
        return super().usage_totals(day)


class BrokenLedger:
    """A ledger whose database is locked: every call raises, as SQLite would."""

    def __init__(self):
        self.calls = 0

    def add_usage(self, day, key, tokens):
        self.calls += 1
        raise sqlite3.OperationalError("database is locked")

    def usage_totals(self, day):
        self.calls += 1
        raise sqlite3.OperationalError("database is locked")


class BlockingLedger(MemoryLedger):
    """A ledger whose writes block (in their worker thread) until the test releases them."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.threads: set[int] = set()

    def add_usage(self, day, key, tokens):
        self.threads.add(threading.get_ident())
        assert self.release.wait(5), "the test never released the write"
        super().add_usage(day, key, tokens)


class StartedDecider(FakeDecider):
    """A FakeDecider that signals when a call has begun."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = asyncio.Event()

    async def decide(self, state, questions, **kwargs):
        self.started.set()
        return await super().decide(state, questions, **kwargs)


class GatedReadLedger(MemoryLedger):
    """A ledger whose read signals it has begun, then blocks until the test releases it."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def usage_totals(self, day):
        self.entered.set()
        assert self.release.wait(5), "the test never released the read"
        return super().usage_totals(day)


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


@pytest.fixture
def result(load_fixture):
    base = DecisionResult.model_validate(load_fixture("jev_all_types.response.json"))
    return base.model_copy(update={"usage": Usage(input_tokens=1000, output_tokens=5)})


NOON = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


async def test_the_meter_counts_per_key_and_in_total():
    meter = UsageMeter(MemoryLedger(), now=Clock(NOON))
    await meter.add("a", 10)
    await meter.add("a", 5)
    await meter.add("b", 1)
    assert (meter.tokens("a"), meter.tokens("b"), meter.tokens("c"), meter.total()) == (
        15,
        1,
        0,
        16,
    )


async def test_the_meter_writes_through_and_a_new_meter_resumes_the_day():
    ledger = MemoryLedger()
    first = UsageMeter(ledger, now=Clock(NOON))
    await first.add("a", 40)
    assert ledger.rows == {("2026-10-16", "a"): 40}
    second = UsageMeter(ledger, now=Clock(NOON))  # a restart
    await second.load()
    assert (second.total(), second.tokens("a")) == (40, 40)
    await second.add("a", 2)
    assert ledger.rows[("2026-10-16", "a")] == 42


async def test_load_is_idempotent_and_the_only_read():
    ledger = SpyLedger()
    ledger.rows[("2026-10-16", "a")] = 40
    meter = UsageMeter(ledger, now=Clock(NOON))
    assert ledger.reads == []  # the constructor does no I/O
    await meter.load()
    await meter.load()
    await meter.add("a", 2)
    meter.note("a", 1)
    assert (meter.total(), meter.tokens("a"), meter.tokens("b")) == (43, 43, 0)
    assert ledger.reads == ["2026-10-16"]
    await meter.flush()
    assert ledger.rows[("2026-10-16", "a")] == 43


async def test_reads_never_touch_the_ledger():
    ledger = SpyLedger()
    ledger.rows[("2026-10-16", "a")] = 40
    meter = UsageMeter(ledger, now=Clock(NOON))
    assert (meter.total(), meter.tokens("a")) == (0, 0)  # not loaded: memory only
    await meter.add("a", 1)
    meter.note("a", 1)
    assert ledger.reads == []


async def test_a_load_after_counting_keeps_the_larger_count():
    ledger = MemoryLedger()
    ledger.rows[("2026-10-16", "a")] = 40
    meter = UsageMeter(ledger, now=Clock(NOON))
    meter.note("b", 5)  # counted (and being written) before the load ran
    await meter.load()
    await meter.flush()
    assert (meter.tokens("a"), meter.tokens("b"), meter.total()) == (40, 5, 45)


async def test_midnight_starts_a_fresh_day():
    clock = Clock(datetime(2026, 10, 16, 23, 59, 59, tzinfo=UTC))
    ledger = SpyLedger()
    meter = UsageMeter(ledger, now=clock)
    await meter.load()
    await meter.add("a", 100)
    clock.at += timedelta(seconds=1)
    assert (meter.day(), meter.total(), meter.tokens("a")) == ("2026-10-17", 0, 0)
    await meter.add("a", 7)
    assert ledger.rows == {("2026-10-16", "a"): 100, ("2026-10-17", "a"): 7}
    assert ledger.reads == ["2026-10-16"]  # the new day started empty, with no read


async def test_the_day_is_the_utc_date_whatever_the_clock_zone():
    # 19:00 on the 17th at UTC+10 is 09:00 UTC on the 17th
    plus_ten = datetime(2026, 10, 17, 9, 0, tzinfo=UTC).astimezone(timezone(timedelta(hours=10)))
    assert UsageMeter(None, now=Clock(plus_ten)).day() == "2026-10-17"
    early = datetime(2026, 10, 17, 1, 0, tzinfo=timezone(timedelta(hours=5)))  # 20:00 the 16th
    assert UsageMeter(None, now=Clock(early)).day() == "2026-10-16"
    assert UsageMeter(None, now=Clock(datetime(5, 1, 2, tzinfo=UTC))).day() == "0005-01-02"


async def test_concurrent_adds_are_all_counted():
    meter = UsageMeter(MemoryLedger(), now=Clock(NOON))
    await asyncio.gather(*(meter.add("a", 3) for _ in range(50)))
    assert meter.total() == 150


async def test_a_load_in_flight_across_midnight_does_not_resume_the_old_day():
    clock = Clock(datetime(2026, 10, 16, 23, 59, 59, tzinfo=UTC))
    ledger = GatedReadLedger()
    ledger.rows[("2026-10-16", "a")] = 40
    meter = UsageMeter(ledger, now=clock)
    loading = asyncio.create_task(meter.load())
    try:
        assert await asyncio.to_thread(ledger.entered.wait, 5)  # reading the 16th now
        clock.at += timedelta(seconds=1)
    finally:
        ledger.release.set()
    meter.note("a", 2)  # the new day is entered while the old day's totals are loading
    await loading
    await meter.flush()
    assert (meter.day(), meter.total()) == ("2026-10-17", 2)


async def test_a_meter_without_a_ledger_still_counts_in_memory():
    meter = UsageMeter(None, now=Clock(NOON))
    await meter.add("a", 9)
    assert meter.total() == 9


@pytest.mark.parametrize("tokens", [0, -5])
async def test_the_meter_never_passes_a_non_positive_count_to_the_ledger(tokens):
    ledger = MemoryLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    await meter.add("a", tokens)
    assert (meter.total(), ledger.rows) == (1, {("2026-10-16", "a"): 1})


async def test_a_failing_ledger_leaves_memory_counting(caplog):
    ledger = BrokenLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    with caplog.at_level(logging.WARNING, logger="gumshoe.decider.shadow.budget"):
        await meter.load()
        assert meter.total() == 0
        await meter.add("a", 9)
        await meter.add("a", 1)
        assert (meter.total(), meter.tokens("a")) == (10, 10)
    assert ledger.calls == 3  # the load and both writes were tried
    assert "OperationalError" in caplog.text
    assert "database is locked" not in caplog.text  # the type only, never the message


async def test_a_failing_load_starts_the_day_at_zero_and_does_not_raise():
    meter = UsageMeter(BrokenLedger(), now=Clock(NOON))
    await meter.load()
    assert meter.total() == 0
    await meter.add("a", 4)
    assert meter.tokens("a") == 4


async def test_a_metered_decider_counts_the_reported_input_tokens_under_the_client_key(result):
    ledger = MemoryLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    decider = MeteredDecider(FakeDecider("jev", result), meter)
    assert decider.name == "jev"
    client_key.set("1.1.1.1")
    try:
        assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="intent") is result
    finally:
        client_key.set("")
    assert meter.tokens("1.1.1.1") == 1000 and meter.total() == 1000
    await meter.flush()
    assert ledger.rows == {("2026-10-16", "1.1.1.1"): 1000}


async def test_a_call_with_no_usage_counts_an_estimate(result):
    bare = result.model_copy(update={"usage": None})
    meter = UsageMeter(None, now=Clock(NOON))
    await MeteredDecider(FakeDecider("jev", bare), meter).decide(DEMO_STATE, DEMO_QUESTIONS)
    assert meter.total() >= 1


async def test_a_call_reporting_zero_input_tokens_still_counts_one(result):
    zero = result.model_copy(update={"usage": Usage(input_tokens=0, output_tokens=0)})
    meter = UsageMeter(None, now=Clock(NOON))
    await MeteredDecider(FakeDecider("jev", zero), meter).decide(DEMO_STATE, DEMO_QUESTIONS)
    assert meter.total() == 1


async def test_a_failed_call_counts_an_estimate_and_still_raises():
    meter = UsageMeter(None, now=Clock(NOON))
    decider = MeteredDecider(FakeDecider("jev", error=DeciderError("jev", "down")), meter)
    with pytest.raises(DeciderError):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert meter.total() >= 1


async def test_a_cancelled_call_counts_an_estimate_and_still_cancels(result):
    gate = asyncio.Event()
    ledger = MemoryLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    inner = StartedDecider("jev", result, gate=gate)
    decider = MeteredDecider(inner, meter)
    task = asyncio.create_task(decider.decide(DEMO_STATE, DEMO_QUESTIONS))
    await inner.started.wait()  # the call is in flight
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner.cancelled.is_set()
    estimate = estimate_tokens(DEMO_STATE, DEMO_QUESTIONS)
    assert meter.total() == estimate  # it may have been billed: counted at once, no await
    await meter.flush()
    assert ledger.rows == {("2026-10-16", ""): estimate}


async def test_a_broken_ledger_never_fails_the_decision(result):
    meter = UsageMeter(BrokenLedger(), now=Clock(NOON))
    decider = MeteredDecider(FakeDecider("jev", result), meter)
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
    await meter.flush()
    assert meter.total() == 2000


async def test_a_broken_ledger_keeps_a_failed_call_s_own_error():
    meter = UsageMeter(BrokenLedger(), now=Clock(NOON))
    decider = MeteredDecider(FakeDecider("jev", error=DeciderError("jev", "down")), meter)
    with pytest.raises(DeciderError):
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await meter.flush()
    assert meter.total() >= 1


async def test_a_slow_ledger_write_never_delays_the_decision(result):
    ledger = BlockingLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    decider = MeteredDecider(FakeDecider("jev", result), meter)
    try:
        assert await decider.decide(DEMO_STATE, DEMO_QUESTIONS) is result
        assert meter.total() == 1000  # counted in memory while the write is still blocked
        assert ledger.rows == {}
    finally:
        ledger.release.set()
    await meter.flush()
    assert ledger.rows == {("2026-10-16", ""): 1000}
    assert threading.get_ident() not in ledger.threads  # written off the event loop


async def test_aclose_closes_the_inner_decider_and_flushes_the_writes(result):
    inner = FakeDecider("jev", result)
    ledger = MemoryLedger()
    decider = MeteredDecider(inner, UsageMeter(ledger, now=Clock(NOON)))
    await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
    await decider.aclose()
    assert inner.closed
    assert ledger.rows == {("2026-10-16", ""): 1000}


async def test_aclose_gives_up_on_a_hanging_ledger_write_after_the_grace(result, caplog):
    inner = FakeDecider("jev", result)
    ledger = BlockingLedger()
    meter = UsageMeter(ledger, now=Clock(NOON))
    decider = MeteredDecider(inner, meter, flush_grace_s=0.01)
    try:
        await decider.decide(DEMO_STATE, DEMO_QUESTIONS)
        with caplog.at_level(logging.WARNING, logger="gumshoe.decider.shadow.budget"):
            await decider.aclose()  # returns although the write is still blocked
        assert inner.closed
        assert ledger.rows == {}
        assert "still pending" in caplog.text
    finally:
        ledger.release.set()
