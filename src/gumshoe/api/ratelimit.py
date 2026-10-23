"""Rate limits and the turn gate. In memory, one process: see the spec's risks."""

import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable

from gumshoe.api.errors import ApiError
from gumshoe.config import Settings


class WindowLimiter:
    """At most `limit` hits per `window_s` per key (a sliding window). `limit == 0` is unlimited.

    The table holds at most `max_keys` keys. Only keys whose window has passed are ever evicted;
    when every key is live a new key is refused (fail closed), so a flood of fresh keys cannot
    push a real client's counter out."""

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

    def hit(self, key: str) -> int | None:
        """None when allowed (the hit is recorded); else the seconds until it would be."""
        if self._limit == 0:
            return None
        now = self._clock()
        hits = self._expire(key, now)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._sweep(now)
            if len(self._hits) >= self._max_keys:
                return math.ceil(self._window)
            hits = self._hits[key] = deque()
        if len(hits) >= self._limit:
            return max(1, math.ceil(hits[0] + self._window - now))
        hits.append(now)
        return None


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
    """The rate limits, each raising a 429 with Retry-After."""

    def __init__(self, settings: Settings, *, clock: Callable[[], float] = time.monotonic) -> None:
        keys = settings.limiter_max_keys

        def make(limit: int, window: float) -> WindowLimiter:
            return WindowLimiter(limit, window, clock=clock, max_keys=keys)

        self._requests = make(settings.ip_requests_per_minute, 60)
        self._new_sessions = make(settings.ip_new_sessions_per_hour, 3600)
        self._ip_turns = make(settings.ip_turns_per_minute, 60)
        self._games_created = make(settings.session_games_per_hour, 3600)
        self._session_turns = make(settings.session_turns_per_minute, 60)

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
