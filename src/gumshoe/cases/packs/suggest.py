"""Did-you-mean text for unknown keys (deterministic: sorted candidates, stdlib difflib)."""

from collections.abc import Iterable
from difflib import get_close_matches


def did_you_mean(word: str, known: Iterable[str]) -> str:
    options = sorted(set(known))
    close = get_close_matches(word, options, n=1, cutoff=0.6)
    hint = f"did you mean {close[0]!r}? " if close else ""
    return f"{hint}known: {', '.join(options) if options else 'none'}"
