"""'Reads everything, then guesses': the exact win probability of a player with no deduction."""

from collections.abc import Sequence
from fractions import Fraction
from itertools import product

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.state import MAX_ATTEMPTS
from gumshoe.cases.rules import gate
from gumshoe.cases.simulate.oracle import read_everything

Triple3 = tuple[str, ...]


def _hits(a: Triple3, b: Triple3) -> int:
    return sum(x == y for x, y in zip(a, b, strict=True))


def guess_win_probability(
    permitted: Sequence[Sequence[str]], truth: Triple3, attempts: int = MAX_ATTEMPTS
) -> Fraction:
    """Each attempt picks uniformly among triples still consistent with the count-only feedback
    so far; a tried triple is never tried again. Exact, no randomness."""
    memo: dict[tuple[frozenset[Triple3], int], Fraction] = {}

    def win(pool: frozenset[Triple3], left: int) -> Fraction:
        if left == 0 or not pool:
            return Fraction(0)
        key = (pool, left)
        if key not in memo:
            total = Fraction(0)
            for guess in sorted(pool):
                if guess == truth:
                    total += 1
                    continue
                score = _hits(guess, truth)
                rest = frozenset(g for g in pool if g != guess and _hits(g, guess) == score)
                total += win(rest, left - 1)
            memo[key] = total / len(pool)
        return memo[key]

    return win(frozenset(product(*permitted)), attempts)


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
