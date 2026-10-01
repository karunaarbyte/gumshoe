"""The Case: immutable, serialisable, entity lists sorted by id."""

from typing import Protocol

from pydantic import field_validator

from gumshoe.cases.model.entities import (
    Event,
    Fact,
    Frozen,
    Location,
    Method,
    Motive,
    PackRef,
    RecordSource,
    Spec,
    Start,
    Suspect,
    Truth,
)
from gumshoe.cases.model.enums import Origin


class HasId(Protocol):
    @property
    def id(self) -> str: ...


def by_id[T: HasId](items: tuple[T, ...]) -> tuple[T, ...]:
    return tuple(sorted(items, key=lambda item: item.id))


class Case(Frozen):
    # meta (not in the digest)
    id: str
    seed: int | None = None
    schema_version: int = 1
    origin: Origin = Origin.GENERATED
    pack_ref: PackRef | None = None
    generator_version: str | None = None
    skeleton_algo_version: int = 1
    pack_versions: tuple[tuple[str, int], ...] = ()
    attempt: int = 0
    stage_attempts: tuple[int, ...] = ()
    theme: str = ""
    skin_rev: int = 0
    skin_hash: str = ""
    # skeleton
    spec: Spec
    scene_type: str
    truth: Truth
    start: Start
    suspects: tuple[Suspect, ...]
    locations: tuple[Location, ...]
    record_sources: tuple[RecordSource, ...]
    methods: tuple[Method, ...]
    motives: tuple[Motive, ...]
    timeline: tuple[Event, ...]
    facts: tuple[Fact, ...]
    # skin
    intro: str = ""
    smalltalk_allow: tuple[str, ...] = ()

    @field_validator(
        "suspects", "locations", "methods", "motives", "timeline", "facts", mode="after"
    )
    @classmethod
    def _sorted_by_id[T: HasId](cls, value: tuple[T, ...]) -> tuple[T, ...]:
        return by_id(value)

    @field_validator("record_sources", mode="after")
    @classmethod
    def _sorted_sources(cls, value: tuple[RecordSource, ...]) -> tuple[RecordSource, ...]:
        return tuple(
            sorted(value, key=lambda r: (r.kind, r.subject, r.subject_type.value, r.requires))
        )

    @field_validator("smalltalk_allow", mode="after")
    @classmethod
    def _sorted_words(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(value))

    @field_validator("pack_versions", mode="after")
    @classmethod
    def _sorted_versions(cls, value: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(value))
