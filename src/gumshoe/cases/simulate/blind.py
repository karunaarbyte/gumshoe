"""'Reads everything, then guesses': the exact win probability of a player with no deduction."""

from collections.abc import Sequence
from fractions import Fraction
from functools import lru_cache
from itertools import product

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.state import MAX_ATTEMPTS
from gumshoe.cases.rules import gate
from gumshoe.cases.simulate.oracle import read_everything

Triple3 = tuple[str, ...]
TRUTH = "truth"


def _hits(a: Triple3, b: Triple3) -> int:
    return sum(x == y for x, y in zip(a, b, strict=True))


def guess_win_probability(
    permitted: Sequence[Sequence[str]], truth: Triple3, attempts: int = MAX_ATTEMPTS
) -> Fraction:
    """Each attempt picks uniformly among triples still consistent with the count-only feedback
    so far; a tried triple is never tried again. Exact, no randomness.

    Names do not matter, only each axis's pool size and whether the truth is in it, so the
    work is done once per such shape (see `_canonical_win`)."""
    pools = [frozenset(p) for p in permitted]
    sizes = tuple(len(p) for p in pools)
    truth_in = tuple(t in p for t, p in zip(truth, pools, strict=True))
    return _canonical_win(sizes, truth_in, attempts)


@lru_cache(maxsize=256)
def _canonical_win(sizes: tuple[int, ...], truth_in: tuple[bool, ...], attempts: int) -> Fraction:
    """The win probability over symbolic candidates: "truth" (where it is in the pool) and
    "other_i". The full pool is symmetric in each axis's others, so a first guess is worth the
    same as any other guess that matches the truth on the same axes: one is evaluated per
    pattern of matches and weighted by how many guesses share it."""
    axes = [
        ([TRUTH] if inside else []) + [f"other_{i}" for i in range(n - inside)]
        for n, inside in zip(sizes, truth_in, strict=True)
    ]
    truth = tuple(TRUTH for _ in sizes)
    pool = frozenset(product(*axes))
    if attempts <= 0 or not pool:
        return Fraction(0)
    patterns: dict[tuple[bool, ...], list[Triple3]] = {}
    for guess in sorted(pool):
        patterns.setdefault(tuple(g == t for g, t in zip(guess, truth, strict=True)), []).append(
            guess
        )
    memo: dict[tuple[frozenset[Triple3], int], Fraction] = {}
    total = Fraction(0)
    for members in patterns.values():
        total += len(members) * _after(members[0], pool, truth, attempts, memo)
    return total / len(pool)


def _after(
    guess: Triple3,
    pool: frozenset[Triple3],
    truth: Triple3,
    left: int,
    memo: dict[tuple[frozenset[Triple3], int], Fraction],
) -> Fraction:
    """The chance of winning from this guess on (it uses one of the `left` attempts)."""
    if guess == truth:
        return Fraction(1)
    score = _hits(guess, truth)
    rest = frozenset(g for g in pool if g != guess and _hits(g, guess) == score)
    return _win(rest, truth, left - 1, memo)


def _win(
    pool: frozenset[Triple3],
    truth: Triple3,
    left: int,
    memo: dict[tuple[frozenset[Triple3], int], Fraction],
) -> Fraction:
    if left == 0 or not pool:
        return Fraction(0)
    if left == 1:  # one last pick: a hit only if it is the truth
        return Fraction(int(truth in pool), len(pool))
    key = (pool, left)
    if key not in memo:
        total = sum((_after(g, pool, truth, left, memo) for g in sorted(pool)), Fraction(0))
        memo[key] = total / len(pool)
    return memo[key]


def blind_guess_win_probability(case: Case) -> Fraction:
    """Read every source, then guess among the candidates the gate permits (warnings ignored)."""
    ix = CaseIndex.of(case)
    held = read_everything(ix).held
    permitted = [
        [c for c in ix.candidates[axis] if gate.permission(ix, held, axis, c).allowed]
        for axis in Axis
    ]
    truth = (case.truth.who, case.truth.how, case.truth.why)
    return guess_win_probability(permitted, truth)
