"""Frozen entity models. Skeleton vs skin classification lives in roles.py."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gumshoe.cases.model.enums import (
    Axis,
    ClaimKind,
    EffectKind,
    FactKind,
    RecordSubjectType,
    SourceKind,
)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def sort_strs(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(values))


class Effect(Frozen):
    axis: Axis
    candidate: str
    kind: EffectKind


class Claim(Frozen):
    kind: ClaimKind
    actor: str
    slot: int = Field(ge=0)
    place: str | None = None
    record_kind: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind is ClaimKind.PRESENCE:
            if self.place is None or self.record_kind is not None:
                raise ValueError("a presence claim needs a place and no record kind")
        elif self.record_kind is None or self.place is not None:
            raise ValueError("a record_ref claim needs a record kind and no place")
        return self


class SourceRef(Frozen):
    """Where a fact is found. search: target = location id; interrogate: target = suspect id;
    record: target = record kind key and subject = the record's subject id."""

    kind: SourceKind
    target: str
    subject: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind is SourceKind.RECORD and self.subject is None:
            raise ValueError("a record source needs a subject")
        if self.kind is not SourceKind.RECORD and self.subject is not None:
            raise ValueError("only record sources have a subject")
        return self


class Fact(Frozen):
    id: str
    kind: FactKind
    source: SourceRef
    requires: tuple[str, ...] = ()
    effects: tuple[Effect, ...] = ()
    topic: str | None = None
    trace_kind: str | None = None  # pack trace kind; only on TRACE and ABSENT_TRACE facts
    claim: Claim | None = None
    truthful: bool = True
    speaker: str | None = None
    exposed_by: tuple[str, ...] = ()
    exposure_hook: SourceRef | None = None
    timeline_ref: tuple[str, ...] = ()
    text: str = ""  # skin
    contradiction: str | None = None  # skin, on lies

    @field_validator("requires", "exposed_by", "timeline_ref", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)

    @field_validator("effects", mode="after")
    @classmethod
    def _sorted_effects(cls, value: tuple[Effect, ...]) -> tuple[Effect, ...]:
        return tuple(sorted(value, key=lambda e: (e.axis.value, e.candidate, e.kind.value)))


class Suspect(Frozen):
    id: str
    label: str
    aliases: tuple[str, ...] = ()
    role: str
    motive: str  # id of the motive this suspect's secret realises
    secret_fact: str  # id of the fact that reveals the secret
    requires: tuple[str, ...] = ()  # access gate
    knows: tuple[str, ...] = ()  # facts the suspect can speak
    # skin
    display_name: str = ""
    description: str = ""
    traits: tuple[str, ...] = ()
    style: str = ""
    secret_text: str = ""

    @field_validator("aliases", "requires", "knows", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Location(Frozen):
    id: str
    kind: str
    aliases: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    decorative: bool = False
    # skin
    name: str = ""
    description: str = ""

    @field_validator("aliases", "requires", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class RecordSource(Frozen):
    """A record kind about one subject: the unit a `record(kind, subject)` source refers to."""

    kind: str
    subject_type: RecordSubjectType
    subject: str
    requires: tuple[str, ...] = ()

    @field_validator("requires", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Method(Frozen):
    id: str
    label: str
    aliases: tuple[str, ...] = ()
    type: str = ""  # pack method key

    @field_validator("aliases", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Motive(Frozen):
    id: str
    label: str
    aliases: tuple[str, ...] = ()
    type: str = ""  # pack motive key

    @field_validator("aliases", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Event(Frozen):
    id: str
    slot: int = Field(ge=0)
    actor: str
    place: str
    action: str


class Truth(Frozen):
    who: str
    how: str
    why: str


class Start(Frozen):
    locations: tuple[str, ...] = ()
    suspects: tuple[str, ...] = ()
    facts: tuple[str, ...] = ()

    @field_validator("locations", "suspects", "facts", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Limits(Frozen):
    """Difficulty window the validator reads from the case itself (integers only)."""

    solution_min: int
    solution_max: int
    depth_min: int
    depth_max: int
    actions_min: int
    actions_max: int
    decisive_pct_max: int


class Spec(Frozen):
    preset: str
    suspects: int = Field(ge=0)
    methods: int = Field(ge=0)
    motives: int = Field(ge=0)
    locations: int = Field(ge=0)
    record_kinds: int = Field(ge=0)
    slots: int = Field(ge=0)
    source_cap: int = 4
    fairness_tolerance: int = 1
    limits: Limits


class PackRef(Frozen):
    id: str
    skeleton_hash: str
