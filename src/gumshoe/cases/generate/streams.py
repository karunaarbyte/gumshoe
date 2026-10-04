"""Deterministic streams: a sha256 counter-mode generator with its own sampling primitives.

CPython guarantees reproducible output only for `random.random` and `seed`, and `shuffle`,
`sample` and `randrange` have changed between versions, so nothing here uses `random`. Block `i`
of a stream is `sha256(DOMAIN || key || i)`; the key is the canonical JSON of the stream's
identity, so a stream is a pure function of that identity and never of another stream's position.
"""

from collections.abc import Sequence
from hashlib import sha256
from typing import Self

from gumshoe.cases.core.canonical import canonical_json

DOMAIN = b"gumshoe.stream.v1"
_U64 = 2**64


def _sequence[T](items: Sequence[T]) -> Sequence[T]:
    """Only real sequences: a set or frozenset has hash-based order, a str is a trap."""
    if isinstance(items, str) or not isinstance(items, Sequence):
        raise TypeError(f"streams accept only sequences, not {type(items).__name__}")
    return items


class Stream:
    def __init__(self, key: bytes) -> None:
        self._key = key
        self._block = 0
        self._buffer = b""

    @classmethod
    def root(cls, seed: int, spec_hash: str, stage_version: int, counter: int, label: str) -> Self:
        identity = [seed, spec_hash, stage_version, counter, [label]]
        return cls(canonical_json(identity))

    def child(self, label: str) -> "Stream":
        """A sub-stream keyed by this stream's key and the label, never by its position."""
        return Stream(canonical_json([self._key.decode("utf-8"), label]))

    def _u64(self) -> int:
        while len(self._buffer) < 8:
            counter = self._block.to_bytes(8, "big")
            self._buffer += sha256(DOMAIN + self._key + counter).digest()
            self._block += 1
        value = int.from_bytes(self._buffer[:8], "big")
        self._buffer = self._buffer[8:]
        return value

    def below(self, n: int) -> int:
        """Uniform in [0, n) by rejection: no modulo bias. n == 1 consumes nothing."""
        if n <= 0:
            raise ValueError("below() needs a positive bound")
        if n == 1:
            return 0
        limit = _U64 - _U64 % n
        while True:
            x = self._u64()
            if x < limit:
                return x % n

    def choice[T](self, items: Sequence[T]) -> T:
        seq = _sequence(items)
        return seq[self.below(len(seq))]

    def shuffle[T](self, items: Sequence[T]) -> list[T]:
        """Fisher-Yates on a copy."""
        out = list(_sequence(items))
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out

    def sample[T](self, items: Sequence[T], k: int) -> list[T]:
        """k distinct items in drawn order (a partial Fisher-Yates on a copy)."""
        out = list(_sequence(items))
        if not 0 <= k <= len(out):
            raise ValueError("sample() size is outside the sequence")
        for i in range(k):
            j = i + self.below(len(out) - i)
            out[i], out[j] = out[j], out[i]
        return out[:k]

    def rank(self, keys: Sequence[str], label: str) -> list[str]:
        """Rendezvous hashing: the keys best first. A key's score depends only on this stream's
        key, the label and the key itself, never on the other keys or on the stream's position,
        so adding or removing a pool entry moves only that entry."""
        base = self._key.decode("utf-8")
        scored = [
            (sha256(DOMAIN + canonical_json(["rank", base, label, k])).digest(), k)
            for k in _sequence(keys)
        ]
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [k for _, k in scored]
