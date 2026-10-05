"""Stage outputs: frozen, built only from strings, ints, bools and tuples, each with a digest.

Entities carry neutral pool positions ("s0", "m1", "v2", "l0"), never final ids: the permutation
that hides them comes in 2d-3. `TruthOut` is the only output where a position means something:
`s0`, `m0` and `v0` are the culprit, the method and the motive of the truth.
"""

from typing import Literal

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
    """The roster reordered so the culprit is s0, the true method m0 and the culprit's motive v0.

    After the renumbering suspect s_k always has motive v_k (motive_pos is the identity mapping),
    so the 2d-3 permutation must permute suspects and motives independently, or rely on hashed
    ids, so that pattern never reaches a case.
    """

    roster: RosterOut
    who_pos: Literal["s0"] = "s0"
    how_pos: Literal["m0"] = "m0"
    why_pos: Literal["v0"] = "v0"


class TimelineRow(Frozen):
    suspect_pos: str
    places: tuple[str, ...]  # location pos per slot, index = slot


class TimelineOut(Output):
    crime_slot: int
    rows: tuple[TimelineRow, ...]  # every suspect in every slot
    opportunity: tuple[str, ...]  # the wrong suspects at the scene (l0) in the crime slot


class EffectDesc(Frozen):
    axis: str  # "who" | "how" | "why"
    candidate: str  # a neutral position: s0, m1, v2
    kind: str  # "rules_out" | "supports" | "proves"


class ClaimDesc(Frozen):
    """A presence claim: `actor` was at the location `place` in time slot `slot`."""

    actor: str
    slot: int
    place: str


class HomeDesc(Frozen):
    """Where a fact is found. `kind` is "record", "interrogate" or "search". A record's `target`
    is its record kind and its `subject` a suspect or location position (None until placement
    picks it); an interrogation's `target` is the suspect; a search fact has no home yet."""

    kind: str
    target: str | None = None
    subject: str | None = None


class FactDesc(Frozen):
    """One fact. The id prefixes are a contract the later stages rely on: sec (secret), e
    (presence or alibi at the crime slot), x (physical item), w (second presence), y (the motive
    hint a suspect gives; it gates their record), l (the lie), h (decisive trace), p (its clue),
    c (a key that unlocks questioning a suspect), n (neutral location-record entry), each
    followed by `_<position or kind>`."""

    id: str
    kind: str  # a `FactKind` value
    effects: tuple[EffectDesc, ...] = ()
    claim: ClaimDesc | None = None
    truthful: bool = True
    speaker: str | None = None
    exposed_by: tuple[str, ...] = ()
    exposure_hook: HomeDesc | None = None
    timeline_ref: tuple[str, ...] = ()  # event ids "e_<pos>_<slot>"
    trace_kind: str | None = None
    requires: tuple[str, ...] = ()  # only a decisive trace requires its supporting clue
    home: HomeDesc
    place_kinds: tuple[str, ...] = ()  # a search fact: the location kinds it may be found in
    apart_from: str | None = None  # a search fact: another fact it must not share a location with


class RecordSourceDesc(Frozen):
    kind: str
    subject_type: str  # "suspect" | "location"
    subject: str | None  # None for a location record until placement picks the location


class FactsOut(Output):
    depth: int  # the gating depth, one value for every suspect
    facts: tuple[FactDesc, ...]
    record_sources: tuple[RecordSourceDesc, ...]


class PlacedFact(Frozen):
    """A search fact and the location it is found at."""

    fact: str
    location: str  # a location position: l0 is the scene


class PlacedRecord(Frozen):
    """A record source whose subject is now known (a suspect, or the location a record is about)."""

    kind: str
    subject_type: str  # "suspect" | "location"
    subject: str


class PlacementOut(Output):
    search: tuple[PlacedFact, ...]  # every search fact, sorted by fact id
    record_sources: tuple[PlacedRecord, ...]  # the suspects' records, then the location records


class SuspectGate(Frozen):
    """Questioning `suspect` needs the fact `fact` (at depth 2, the suspect's key)."""

    suspect: str
    fact: str


class RecordGate(Frozen):
    """Reading the record source `(kind, subject)` needs the fact `fact` (the suspect's hint)."""

    kind: str
    subject: str
    fact: str


class GatingOut(Output):
    depth: int
    suspect_requires: tuple[SuspectGate, ...]  # sorted by suspect
    record_requires: tuple[RecordGate, ...]  # sorted by (kind, subject)
    start_locations: tuple[str, ...]
    start_suspects: tuple[str, ...]  # the suspects nobody has to unlock
    start_facts: tuple[str, ...]  # always empty here: no fact is known at the start
