"""While the castle's wording is written chunk by chunk, stage 8 reports exactly what is missing."""

from gumshoe.cases.packs.check import skin_inputs
from gumshoe.cases.tools.builtin import load_builtin_pack

# Each chunk of plan 2c.1b removes its prefix from this tuple; the last one empties it.
PENDING: tuple[str, ...] = ()


def _paths() -> list[str]:
    return [issue.path for issue in skin_inputs.check(load_builtin_pack("castle"))]


def test_every_gap_belongs_to_a_chunk_that_is_still_pending():
    assert [p for p in _paths() if not p.startswith(PENDING)] == []
