import pytest

from gumshoe.api.errors import ApiError
from gumshoe.api.ratelimit import Quotas, WindowLimiter, client_ip
from gumshoe.config import Settings
from tests.decider.fakes import FakeClock


def limiter(limit=2, window=60.0, clock=None, max_keys=100):
    return WindowLimiter(limit, window, clock=clock or FakeClock(), max_keys=max_keys)


def test_hits_up_to_the_limit_pass_and_the_next_is_told_how_long_to_wait():
    clock = FakeClock()
    lim = limiter(clock=clock)
    assert lim.hit("a") is None and lim.hit("a") is None
    clock.advance(10)
    assert lim.hit("a") == 50  # the first hit leaves the window 50 s from now


def test_the_window_slides():
    clock = FakeClock()
    lim = limiter(clock=clock)
    lim.hit("a")
    clock.advance(30)
    lim.hit("a")
    clock.advance(31)  # the first hit is now 61 s old
    assert lim.hit("a") is None


def test_keys_are_independent_and_a_refused_hit_is_not_recorded():
    clock = FakeClock()
    lim = limiter(limit=1, clock=clock)
    assert lim.hit("a") is None and lim.hit("b") is None
    assert lim.hit("a") is not None
    clock.advance(60)
    assert lim.hit("a") is None  # refused calls did not extend the wait


def test_a_limit_of_zero_is_unlimited():
    lim = limiter(limit=0)
    assert all(lim.hit("a") is None for _ in range(1000))


def test_a_full_table_of_live_keys_refuses_new_keys_but_keeps_the_old_counters():
    clock = FakeClock()
    lim = limiter(limit=1, clock=clock, max_keys=100)
    for i in range(100):
        assert lim.hit(f"k{i}") is None
    assert lim.hit("newcomer") is not None  # fail closed
    assert lim.hit("k0") is not None  # a victim's live counter was not flushed
    clock.advance(61)
    assert lim.hit("newcomer") is None  # expired keys make room again


def test_expired_keys_are_dropped_so_memory_is_bounded():
    clock = FakeClock()
    lim = limiter(limit=1, clock=clock, max_keys=100)
    for round_ in range(5):
        for i in range(100):
            assert lim.hit(f"r{round_}-{i}") is None
        clock.advance(61)


def test_client_ip_uses_the_socket_unless_the_proxy_is_trusted():
    assert client_ip("203.0.113.9", "198.51.100.1", trust_proxy=False) == "203.0.113.9"
    assert client_ip("127.0.0.1", "198.51.100.1", trust_proxy=True) == "198.51.100.1"


def test_the_last_forwarded_entry_is_the_one_the_proxy_added():
    assert client_ip("127.0.0.1", "6.6.6.6, 198.51.100.1", trust_proxy=True) == "198.51.100.1"


def test_a_missing_or_bad_forwarded_header_falls_back_to_the_socket():
    assert client_ip("127.0.0.1", None, trust_proxy=True) == "127.0.0.1"
    assert client_ip("127.0.0.1", "not an ip", trust_proxy=True) == "127.0.0.1"
    assert client_ip(None, None, trust_proxy=False) == "unknown"


def test_an_ipv4_mapped_ipv6_address_is_keyed_as_the_ipv4_address():
    assert client_ip("::ffff:203.0.113.9", None, trust_proxy=False) == "203.0.113.9"
    mapped_10 = client_ip("::ffff:203.0.113.10", None, trust_proxy=False)
    assert mapped_10 != client_ip("::ffff:203.0.113.9", None, trust_proxy=False)


def test_ipv6_addresses_in_one_64_share_a_key():
    a = client_ip("2001:db8:1:2:aaaa::1", None, trust_proxy=False)
    b = client_ip("2001:db8:1:2:bbbb::9", None, trust_proxy=False)
    c = client_ip("2001:db8:1:3::1", None, trust_proxy=False)
    assert a == b != c


def quotas(clock=None, **settings):
    return Quotas(Settings(_env_file=None, **settings), clock=clock or FakeClock())


def test_quotas_raise_a_429_with_retry_after():
    q = quotas(ip_requests_per_minute=2)
    q.request("1.1.1.1")
    q.request("1.1.1.1")
    with pytest.raises(ApiError) as caught:
        q.request("1.1.1.1")
    assert (caught.value.status, caught.value.code) == (429, "rate_limited")
    assert caught.value.retry_after and 1 <= caught.value.retry_after <= 60
    q.request("2.2.2.2")  # another IP is unaffected


def test_each_quota_counts_its_own_thing():
    q = quotas(
        ip_new_sessions_per_hour=1,
        session_games_per_hour=1,
        session_turns_per_minute=1,
        ip_turns_per_minute=3,
    )
    q.new_session("1.1.1.1")
    with pytest.raises(ApiError):
        q.new_session("1.1.1.1")
    q.game_created("alice")
    with pytest.raises(ApiError):
        q.game_created("alice")
    q.game_created("bob")
    q.turn("alice", "1.1.1.1")
    with pytest.raises(ApiError):  # alice's per-session turns
        q.turn("alice", "1.1.1.1")
    q.turn("bob", "1.1.1.1")
    q.turn("carol", "1.1.1.1")
    with pytest.raises(ApiError):  # the IP's turns: 3 used (alice, bob, carol)
        q.turn("dave", "1.1.1.1")


def full_table(clock, spy):
    lim = limiter(limit=1, clock=clock, max_keys=100)
    for i in range(100):
        lim.hit(f"k{i}")
    original = lim._sweep

    def counting(now):
        spy.append(now)
        original(now)

    lim._sweep = counting
    return lim


def test_a_full_table_is_not_swept_again_before_anything_can_expire():
    clock = FakeClock()
    sweeps: list[float] = []
    lim = full_table(clock, sweeps)
    assert lim.hit("new0") is not None  # first refusal sweeps once, frees nothing
    for i in range(1, 50):
        clock.advance(1)
        assert lim.hit(f"new{i}") is not None
    assert len(sweeps) == 1


def test_the_refusal_says_when_the_earliest_entry_expires():
    clock = FakeClock()
    lim = full_table(clock, [])
    clock.advance(20)
    assert lim.hit("newcomer") == 40


def test_after_expiry_the_sweep_runs_and_a_new_key_is_admitted():
    clock = FakeClock()
    sweeps: list[float] = []
    lim = full_table(clock, sweeps)
    assert lim.hit("newcomer") is not None
    clock.advance(60)
    assert lim.hit("newcomer") is None
    assert len(sweeps) == 2


def test_a_hit_exactly_one_window_old_has_expired():
    clock = FakeClock()
    lim = limiter(limit=1, clock=clock)
    lim.hit("a")
    clock.advance(59.9)
    assert lim.hit("a") == 1
    clock.advance(0.1)
    assert lim.hit("a") is None


def test_a_refunded_hit_frees_its_place():
    limiter = WindowLimiter(1, 60, clock=FakeClock())
    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    limiter.refund("a")
    assert limiter.hit("a") is None
    limiter.refund("nobody")  # nothing to take back: no error
