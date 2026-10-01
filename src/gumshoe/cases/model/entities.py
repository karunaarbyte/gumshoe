"""Frozen entity models. Skeleton vs skin classification lives in roles.py."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gumshoe.cases.model.enums import Axis, ClaimKind, EffectKind, FactKind, SourceKind


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
