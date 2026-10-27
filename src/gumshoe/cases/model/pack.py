"""The Pack type (data only). Loading from TOML lives in `gumshoe.cases.packs`."""

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, field_validator

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.entities import Frozen, sort_strs


def _sorted_set(value: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(value))


# set-like lists are sorted; wording lists (plain tuple[str, ...]) keep their authored order
SetTexts = Annotated[tuple[str, ...], AfterValidator(_sorted_set)]


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


class Entry(Frozen):
    """A pool entry: a name or noun with the grammar the templates need."""

    text: str = Field(min_length=1)
    article: str | None = None
    plural: bool = False
    pronoun: Literal["he", "she", "they", "it"] | None = None
    proper: bool = False
    prep: str | None = Field(
        default=None, pattern=r"^[a-z]+( [a-z]+)?$"
    )  # what `{place.in}` starts with ("on", "at"); in when unset; read for location names only


class SlotDef(Frozen):
    key: str
    at: str
    during: str


class LocationDef(Frozen):
    key: str
    names: tuple[Entry, ...] = ()
    descriptions: tuple[str, ...] = ()


class RecordDef(Frozen):
    key: str
    subject: Literal["suspect", "location", "event"]
    medium: Literal["written", "token", "oral"]
    presence: tuple[str, ...] = ()
    names: tuple[Entry, ...] = ()  # display names; the first one is what `{record}` renders
    location_kinds: SetTexts = ()  # the kinds of place this record kind can attest
    entries: tuple[str, ...] = ()  # neutral lines a record about a place holds (skin only)


class TraceDef(Frozen):
    kind: str
    location_kinds: SetTexts = ()
    templates: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()  # what the trace would have left and is not there


class MethodDef(Frozen):
    key: str
    label: str
    aliases: SetTexts = ()
    traces: tuple[TraceDef, ...] = ()
    clues: tuple[str, ...] = ()  # supporting texts that belong to this method and hold no trace

    @field_validator("traces", mode="after")
    @classmethod
    def _by_kind(cls, value: tuple[TraceDef, ...]) -> tuple[TraceDef, ...]:
        return tuple(sorted(value, key=lambda t: t.kind))


class MotiveDef(Frozen):
    key: str
    label: str
    aliases: SetTexts = ()
    secrets: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()  # evoke the motive; a secret proves it


class FamilyDef(Frozen):
    id: str
    kind: str
    claim_slots: SetTexts = ()
    variants: tuple[str, ...] = ()


class RoleDef(Frozen):
    key: str
    record_kinds: tuple[str, ...] = ()
    motive_types: tuple[str, ...] = ()  # allow-list of pack motive keys
    names: tuple[Entry, ...] = ()
    traits: tuple[str, ...] = ()
    noun: str = ""  # display noun: a suspect's label is "<name> the <noun>"
    style: str = ""  # how the suspect talks (the persona brief)

    @field_validator("record_kinds", "motive_types", mode="after")
    @classmethod
    def _sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return sort_strs(value)


class Pack(Frozen):
    id: str
    skeleton_rev: int = Field(default=1, ge=1)
    skin_rev: int = Field(default=1, ge=1)
    slots: int = Field(default=4, ge=1)
    presets: SetTexts = ()  # the preset names this pack claims to host
    capacity: Capacity
    scene_types: tuple[SceneType, ...] = ()
    roles: tuple[RoleDef, ...] = ()
    record_kinds: tuple[str, ...] = ()
    slot_defs: tuple[SlotDef, ...] = ()  # time order: never sorted
    location_defs: tuple[LocationDef, ...] = ()
    record_defs: tuple[RecordDef, ...] = ()
    method_defs: tuple[MethodDef, ...] = ()
    motive_defs: tuple[MotiveDef, ...] = ()
    families: tuple[FamilyDef, ...] = ()
    victims: tuple[Entry, ...] = ()  # the lord, with his title: "Lord Aldric"
    smalltalk_allow: SetTexts = ()  # single words `reply_check` never flags

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

    # duplicates are allowed here on purpose: check stage 2 reports them with a key path
    @field_validator("location_defs", "record_defs", "method_defs", "motive_defs", mode="after")
    @classmethod
    def _sorted_defs(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(sorted(value, key=lambda d: d.key))

    @field_validator("families", mode="after")
    @classmethod
    def _sorted_families(cls, value: tuple[FamilyDef, ...]) -> tuple[FamilyDef, ...]:
        return tuple(sorted(value, key=lambda f: f.id))

    @property
    def known_record_kinds(self) -> frozenset[str]:
        return frozenset(self.record_kinds) | {d.key for d in self.record_defs}

    def skeleton_view(self) -> dict[str, Any]:
        """Everything that can change a generated skeleton: structure and pool membership,
        never wording (spec 4.8). Wording lives in descriptions, templates, secrets, traits,
        slot phrases and the variants of a family, and neither its text nor its amount counts."""

        def entries(items: tuple[Entry, ...]) -> list[dict[str, Any]]:
            return [e.model_dump(mode="json", exclude={"prep"}) for e in items]

        return {
            "id": self.id,
            "skeleton_rev": self.skeleton_rev,
            "slots": self.slots,
            "presets": list(self.presets),
            "capacity": self.capacity.model_dump(mode="json"),
            "scene_types": [s.model_dump(mode="json") for s in self.scene_types],
            "record_kinds": list(self.record_kinds),
            "slot_keys": [s.key for s in self.slot_defs],
            "roles": [
                {
                    "key": r.key,
                    "noun": r.noun,
                    "record_kinds": list(r.record_kinds),
                    "motive_types": list(r.motive_types),
                    "names": entries(r.names),
                }
                for r in self.roles
            ],
            "locations": [{"key": d.key, "names": entries(d.names)} for d in self.location_defs],
            "records": [
                {
                    "key": d.key,
                    "subject": d.subject,
                    "medium": d.medium,
                    "location_kinds": list(d.location_kinds),
                }
                for d in self.record_defs
            ],
            "methods": [
                {
                    "key": m.key,
                    "label": m.label,
                    "aliases": list(m.aliases),
                    "traces": [
                        {"kind": t.kind, "location_kinds": list(t.location_kinds)} for t in m.traces
                    ],
                }
                for m in self.method_defs
            ],
            "motives": [
                {"key": m.key, "label": m.label, "aliases": list(m.aliases)}
                for m in self.motive_defs
            ],
            "families": [
                {"id": f.id, "kind": f.kind, "claim_slots": list(f.claim_slots)}
                for f in self.families
            ],
        }

    def skeleton_hash(self) -> str:
        """Digest of everything that can change a generated skeleton (not the wording)."""
        return domain_digest("gumshoe.pack.skeleton.v3", canonical_json(self.skeleton_view()))
