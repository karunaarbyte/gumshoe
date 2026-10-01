"""Predicates for judging whether two candidate labels can be told apart."""

from collections.abc import Iterable

from gumshoe.cases.core.text import normalise, tokens


def token_set(*texts: str) -> frozenset[str]:
    result: set[str] = set()
    for text in texts:
        result.update(tokens(text))
    return frozenset(result)


def overlap_kind(a: str, b: str) -> str | None:
    """How two labels collide: `equal`, `subset` (token sets nested), `substring`, or None."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return None
    if na == nb:
        return "equal"
    ta, tb = frozenset(tokens(a)), frozenset(tokens(b))
    if ta and tb and (ta <= tb or tb <= ta):
        return "subset"
    if na in nb or nb in na:
        return "substring"
    return None


def distinctive(own: frozenset[str], others: Iterable[frozenset[str]]) -> frozenset[str]:
    """Tokens of `own` that no other candidate uses."""
    taken: set[str] = set()
    for other in others:
        taken.update(other)
    return own - taken
