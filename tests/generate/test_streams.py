from collections.abc import Callable
from typing import Any

import pytest

from gumshoe.cases.generate.streams import Stream
from tests.generate.helpers import chi2_critical

GOLDEN_BELOW = [1, 1, 5, 7, 9, 1, 0, 0]
GOLDEN_SHUFFLE = [4, 0, 3, 2, 5, 1]
GOLDEN_SAMPLE = [3, 0, 2]
GOLDEN_CHOICE = "a"
GOLDEN_RANK = ["b", "d", "c", "a"]  # not the sorted order, so a sort would not pass
GOLDEN_CHILD = 98


def root(label: str = "roster", counter: int = 0, seed: int = 7) -> Stream:
    return Stream.root(seed, "spechash", 1, counter, label)


def test_golden_values_pin_every_primitive():
    s = root()
    assert [s.below(10) for _ in range(8)] == GOLDEN_BELOW
    assert s.shuffle(list(range(6))) == GOLDEN_SHUFFLE
    assert s.sample(list(range(10)), 3) == GOLDEN_SAMPLE
    assert s.choice(["a", "b", "c"]) == GOLDEN_CHOICE
    assert root().rank(["a", "b", "c", "d"], "y") == GOLDEN_RANK
    assert root().child("k").below(1000) == GOLDEN_CHILD


def test_the_same_identity_gives_the_same_sequence():
    assert [root().below(1000) for _ in range(3)] == [root().below(1000) for _ in range(3)]
    a, b = root(), root()
    assert [a.below(1000) for _ in range(20)] == [b.below(1000) for _ in range(20)]


@pytest.mark.parametrize(
    "other",
    [root("truth"), root(counter=1), root(seed=8), Stream.root(7, "other", 1, 0, "roster")],
)
def test_any_change_of_identity_changes_the_sequence(other):
    assert [root().below(10**9) for _ in range(4)] != [other.below(10**9) for _ in range(4)]


def test_child_depends_on_the_key_and_label_not_on_the_parents_position():
    fresh, used = root(), root()
    for _ in range(5):
        used.below(1000)
    assert [fresh.child("a").below(10**9) for _ in range(3)] == [
        used.child("a").below(10**9) for _ in range(3)
    ]
    assert fresh.child("a").below(10**9) != fresh.child("b").below(10**9)
    assert fresh.child("a").child("b").below(10**9) != fresh.child("b").child("a").below(10**9)


def test_below_one_consumes_nothing_and_a_bad_bound_raises():
    a, b = root(), root()
    assert a.below(1) == 0
    assert a.below(1000) == b.below(1000)  # the n == 1 call did not advance the stream
    for bad in (0, -3):
        with pytest.raises(ValueError):
            root().below(bad)


def test_below_is_close_to_uniform_on_small_ranges():
    for n in (2, 3, 7):
        s = root(f"u{n}")
        counts = [0] * n
        draws = 6000
        for _ in range(draws):
            counts[s.below(n)] += 1
        expected = draws / n
        statistic = sum((c - expected) ** 2 / expected for c in counts)
        assert statistic < chi2_critical(n - 1), (n, counts)


def test_shuffle_and_sample_return_permutation_and_distinct_items_without_touching_the_input():
    items = list(range(20))
    s = root()
    shuffled = s.shuffle(items)
    assert sorted(shuffled) == items and shuffled != items and items == list(range(20))
    picked = s.sample(items, 5)
    assert len(set(picked)) == 5 and set(picked) <= set(items)
    assert s.sample(items, 0) == [] and sorted(s.sample(items, 20)) == items
    with pytest.raises(ValueError):
        s.sample(items, 21)


def test_primitives_reject_sets_frozensets_and_strings():
    s = root()
    calls: list[Callable[[Any], object]] = [
        s.choice,
        s.shuffle,
        lambda x: s.sample(x, 1),
        lambda x: s.rank(x, "l"),
    ]
    for bad in ({1, 2, 3}, frozenset({1, 2}), "abc"):
        for call in calls:
            with pytest.raises(TypeError):
                call(bad)


def test_rank_does_not_depend_on_the_other_keys_or_the_streams_position():
    keys = [f"k{i}" for i in range(30)]
    a, b = root(), root()
    for _ in range(9):
        b.below(100)
    full = a.rank(keys, "pool")
    assert full == b.rank(keys, "pool") and sorted(full) == sorted(keys)
    without = [k for k in full if k != "k7"]
    assert a.rank([k for k in keys if k != "k7"], "pool") == without  # one entry moves, none else
    assert a.rank(keys, "pool") != a.rank(keys, "other label")


def test_rank_is_close_to_uniform_over_seeds():
    firsts = {k: 0 for k in "abcd"}
    for seed in range(2000):
        firsts[Stream.root(seed, "h", 1, 0, "r").rank(list("abcd"), "x")[0]] += 1
    statistic = sum((c - 500) ** 2 / 500 for c in firsts.values())
    assert statistic < chi2_critical(3), firsts


class Scripted(Stream):
    """A stream whose 64-bit draws are given, to test the rejection rule exactly."""

    def __init__(self, draws: list[int]) -> None:
        super().__init__(b"scripted")
        self._draws = iter(draws)

    def _u64(self) -> int:
        return next(self._draws)


def test_below_rejects_the_draws_that_would_bias_the_result():
    top = 2**64 - 1  # 2**64 % 3 == 1, so this single value is rejected for n == 3
    assert Scripted([top, 5]).below(3) == 2  # the rejected draw is skipped, 5 % 3 == 2
    assert Scripted([top - 1]).below(3) == (top - 1) % 3  # the largest accepted draw is used
