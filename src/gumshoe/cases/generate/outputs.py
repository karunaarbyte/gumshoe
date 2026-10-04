"""Stage outputs: frozen, built only from strings, ints, bools and tuples, each with a digest.

Entities carry neutral pool positions ("s0", "m1", "v2", "l0"), never final ids: the permutation
that hides them comes in 2d-3. `TruthOut` is the only output where a position means something:
`s0`, `m0` and `v0` are the culprit, the method and the motive of the truth.
"""

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.entities import Frozen


class Output(Frozen):
    def digest(self) -> str:
        return domain_digest("gumshoe.gen.output.v1", canonical_json(self.model_dump(mode="json")))


class RosterSuspect(Frozen):
    pos: str
    name: str
    role: str
    noun: str
    label: str
    aliases: tuple[str, ...]
    motive_pos: str
    record_kind: str  # the suspect's secret record kind (owned by the roster)


class RosterMethod(Frozen):
    pos: str
    key: str
    label: str
    aliases: tuple[str, ...]


class RosterMotive(Frozen):
    pos: str
    key: str
    label: str
    aliases: tuple[str, ...]


class RosterLocation(Frozen):
    pos: str
    kind: str
    decorative: bool = False


class RosterOut(Output):
    scene_type: str
    suspects: tuple[RosterSuspect, ...]
    methods: tuple[RosterMethod, ...]
    motives: tuple[RosterMotive, ...]
    locations: tuple[RosterLocation, ...]  # l0 is the scene
    record_kinds: tuple[str, ...]


class TruthOut(Output):
    """The roster reordered so the culprit is s0, the true method m0 and the culprit's motive v0."""

    roster: RosterOut
    who_pos: str = "s0"
    how_pos: str = "m0"
    why_pos: str = "v0"


class TimelineRow(Frozen):
    suspect_pos: str
    places: tuple[str, ...]  # location pos per slot, index = slot


class TimelineOut(Output):
    crime_slot: int
    rows: tuple[TimelineRow, ...]  # every suspect in every slot
    opportunity: tuple[str, ...]  # the wrong suspects at the scene (l0) in the crime slot
