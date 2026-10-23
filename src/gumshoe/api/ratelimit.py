"""Rate limits and the turn gate. In memory, one process: see the spec's risks."""

import asyncio
import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Literal

from fastapi import Request

from gumshoe.api.errors import ApiError
from gumshoe.config import Settings


class WindowLimiter:
    """At most `limit` hits per `window_s` per key (a sliding window). `limit == 0` is unlimited.

    The table holds at most `max_keys` keys. Only keys whose window has passed are ever evicted;
    when every key is live a new key is refused (fail closed), so a flood of fresh keys cannot
    push a real client's counter out. A full table therefore fails closed: new clients get a 429
    until some entry expires. The table is swept at most once per expiry, not once per request."""

    def __init__(
        self,
        limit: int,
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 20000,
    ) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = 0.0  # nothing can expire before this, so a full table need not be swept

    def _expire(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _sweep(self, now: float) -> None:
        for key in list(self._hits):
            self._expire(key, now)
        self._next_sweep = min((h[0] + self._window for h in self._hits.values()), default=0.0)

    def hit(self, key: str) -> int | None:
        """None when allowed (the hit is recorded); else the seconds until it would be."""
        if self._limit == 0:
            return None
        now = self._clock()
        hits = self._expire(key, now)
        if hits is None:
            if len(self._hits) >= self._max_keys and now >= self._next_sweep:
                self._sweep(now)
            if len(self._hits) >= self._max_keys:
                return max(1, math.ceil(self._next_sweep - now))
            hits = self._hits[key] = deque()
        if len(hits) >= self._limit:
            return max(1, math.ceil(hits[0] + self._window - now))
        hits.append(now)
        return None

    def peek(self, key: str) -> int | None:
        """The seconds until `key` may hit again, or None if it may now. Records nothing."""
        if self._limit == 0:
            return None
        now = self._clock()
        hits = self._expire(key, now)
        if hits is None or len(hits) < self._limit:
            return None
        return max(1, math.ceil(hits[0] + self._window - now))


def client_ip(peer: str | None, forwarded: str | None, *, trust_proxy: bool) -> str:
    """The key that stands for a client. IPv6 clients are keyed by their /64 (a home network
    holds billions of addresses). Without `trust_proxy` the forwarded header is ignored."""
    raw = peer
    if trust_proxy and forwarded:
        last = forwarded.split(",")[-1].strip()
        try:
            ipaddress.ip_address(last)
        except ValueError:
            pass
        else:
            raw = last
    if not raw:
        return "unknown"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return raw  # not an address (a test client): used as an opaque key
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped  # a dual-stack socket shows IPv4 clients this way
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
    return str(address)


def _limited(retry_after: int, what: str) -> ApiError:
    message = f"too many {what}; try again soon"
    return ApiError(429, "rate_limited", message, retry_after=retry_after)


class Quotas:
    """The rate limits, each raising a 429 with Retry-After; the admin failures only count, for
    the admin gate's silent block."""

    def __init__(self, settings: Settings, *, clock: Callable[[], float] = time.monotonic) -> None:
        keys = settings.limiter_max_keys

        def make(limit: int, window: float) -> WindowLimiter:
            return WindowLimiter(limit, window, clock=clock, max_keys=keys)

        self._requests = make(settings.ip_requests_per_minute, 60)
        self._new_sessions = make(settings.ip_new_sessions_per_hour, 3600)
        self._ip_turns = make(settings.ip_turns_per_minute, 60)
        self._games_created = make(settings.session_games_per_hour, 3600)
        self._session_turns = make(settings.session_turns_per_minute, 60)
        self._admin_failures = make(10, 60)  # wrong admin tokens: a silent block, never a 429

    @staticmethod
    def _check(limiter: WindowLimiter, key: str, what: str) -> None:
        if (wait := limiter.hit(key)) is not None:
            raise _limited(wait, what)

    def request(self, ip: str) -> None:
        self._check(self._requests, ip, "requests")

    def new_session(self, ip: str) -> None:
        self._check(self._new_sessions, ip, "new players from your network")

    def game_created(self, owner: str) -> None:
        self._check(self._games_created, owner, "new games")

    def turn(self, owner: str, ip: str) -> None:
        self._check(self._session_turns, owner, "turns")
        self._check(self._ip_turns, ip, "turns from your network")

    def admin_blocked(self, ip: str) -> bool:
        """True when `ip` has 10 wrong admin tokens in the last minute."""
        return self._admin_failures.peek(ip) is not None

    def admin_failed(self, ip: str) -> None:
        self._admin_failures.hit(ip)


def request_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    return client_ip(peer, forwarded, trust_proxy=request.app.state.trust_proxy)


class Busy(Exception):
    """Every running and waiting place is taken."""


class Ticket:
    """One turn's place at the gate: reserved by `admit`, then waited on, then closed."""

    def __init__(self, gate: "TurnGate | None") -> None:
        self._gate = gate
        self._state: Literal["queued", "running", "closed"] = "queued"

    async def wait(
        self, abort: asyncio.Event, on_queue: Callable[[int], None] | None = None
    ) -> Literal["ready", "timeout", "left"]:
        gate = self._gate
        if gate is None:
            self._state = "closed"
            return "ready"
        if self._state != "queued":  # waited on or closed already: never wait twice
            return "ready" if self._state == "running" else "left"
        if gate.semaphore.locked() and on_queue is not None:
            # An approximate place: admit order and wait order can differ.
            on_queue(gate.queued)
        acquire = asyncio.ensure_future(gate.semaphore.acquire())
        left = asyncio.ensure_future(abort.wait())
        try:
            done, _ = await asyncio.wait(
                {acquire, left}, timeout=gate.wait_s, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            self._give_up(acquire, left)
            raise
        if acquire in done:  # if abort finished in the same iteration, the slot wins: "ready"
            left.cancel()
            if self._closed():  # closed while waiting: hand the slot straight back
                gate.semaphore.release()
                return "left"
            self._state = "running"
            gate.queued -= 1
            gate.running += 1
            return "ready"
        self._give_up(acquire, left)
        return "left" if left in done else "timeout"

    def _closed(self) -> bool:
        return self._state == "closed"  # a method: close() may run during an await

    def _give_up(self, acquire: "asyncio.Future[Any]", left: "asyncio.Future[Any]") -> None:
        """Synchronous on purpose: a second cancel can never interrupt it half-way."""
        assert self._gate is not None
        sem = self._gate.semaphore
        left.cancel()
        if acquire.done():
            if not acquire.cancelled() and acquire.exception() is None:
                sem.release()  # it won the race: hand the slot back
        else:
            acquire.cancel()

            def _hand_back(fut: "asyncio.Future[Any]") -> None:
                if not fut.cancelled() and fut.exception() is None:
                    sem.release()

            acquire.add_done_callback(_hand_back)
        if self._state == "queued":
            self._gate.queued -= 1
        self._state = "closed"

    def close(self) -> None:
        gate = self._gate
        if gate is not None:
            if self._state == "queued":
                gate.queued -= 1
            elif self._state == "running":
                gate.running -= 1
                gate.semaphore.release()
        self._state = "closed"


class TurnGate:
    """At most `parallel` turns run at once; up to `queue` more may wait, each for at most
    `wait_s`. `parallel == 0` turns the gate off."""

    def __init__(self, parallel: int, queue: int, wait_s: float) -> None:
        self.parallel = parallel
        self.queue = queue
        self.wait_s = wait_s
        self.semaphore = asyncio.Semaphore(max(parallel, 1))
        self.running = 0
        self.queued = 0

    def admit(self) -> Ticket:
        """A place for one turn, or `Busy` at once when running and waiting turns fill the gate."""
        if self.parallel == 0:
            return Ticket(None)
        if self.running + self.queued >= self.parallel + self.queue:
            raise Busy
        self.queued += 1
        return Ticket(self)
