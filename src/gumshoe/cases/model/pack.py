"""The Pack type (data only). Loading from TOML and content live in plan 2c."""

from pydantic import Field, field_validator

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.entities import Frozen, sort_strs


class Capacity(Frozen):
    max_suspects: int = Field(ge=0)
    max_locations: int = Field(ge=0)
    max_methods: int = Field(ge=0)
    max_record_kinds: int = Field(ge=0)


class SceneType(Frozen):
    key: str
    location_kinds: tuple[str, ...] = ()
    allowed_methods: tuple[str, ...] = ()  # pack method keys
    allowed_trace_kinds: tuple[str, ...] = ()

    @field_validator("location_kinds", "allowed_methods", "allowed_trace_kinds", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class RoleDef(Frozen):
    key: str
    record_kinds: tuple[str, ...] = ()
    motive_types: tuple[str, ...] = ()  # allow-list of pack motive keys

    @field_validator("record_kinds", "motive_types", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Pack(Frozen):
    id: str
    skeleton_rev: int = Field(default=1, ge=1)
    skin_rev: int = Field(default=1, ge=1)
    slots: int = Field(default=4, ge=1)
    capacity: Capacity
    scene_types: tuple[SceneType, ...] = ()
    roles: tuple[RoleDef, ...] = ()
    record_kinds: tuple[str, ...] = ()

    @field_validator("record_kinds", mode="after")
    @classmethod
    def _sorted_kinds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)

    @field_validator("scene_types", mode="after")
    @classmethod
    def _sorted_scenes(cls, value: tuple[SceneType, ...]) -> tuple[SceneType, ...]:
        if len({s.key for s in value}) != len(value):
            raise ValueError("duplicate scene type key")
        return tuple(sorted(value, key=lambda s: s.key))

    @field_validator("roles", mode="after")
    @classmethod
    def _sorted_roles(cls, value: tuple[RoleDef, ...]) -> tuple[RoleDef, ...]:
        if len({r.key for r in value}) != len(value):
            raise ValueError("duplicate role key")
        return tuple(sorted(value, key=lambda r: r.key))

    def skeleton_hash(self) -> str:
        """Digest of everything that can change a generated skeleton (not the wording revision)."""
        payload = canonical_json(self.model_dump(mode="json", exclude={"skin_rev"}))
        return domain_digest("gumshoe.pack.skeleton.v1", payload)
