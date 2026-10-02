"""Builders for pack tests."""

from typing import Any

from gumshoe.cases.model.pack import (
    Capacity,
    Entry,
    FamilyDef,
    LocationDef,
    MethodDef,
    MotiveDef,
    Pack,
    RecordDef,
    RoleDef,
    SceneType,
    SlotDef,
    TraceDef,
)

CAPACITY = Capacity(max_suspects=3, max_locations=3, max_methods=3, max_record_kinds=2)


def rich_pack(**changes: Any) -> Pack:
    """A small pack with one of every table, for model tests (not guaranteed check-clean)."""
    fields: dict[str, Any] = {
        "id": "tiny",
        "capacity": CAPACITY,
        "slots": 4,
        "presets": ("tiny",),
        "scene_types": (
            SceneType(
                key="study_murder",
                location_kinds=("study",),
                allowed_methods=("poison",),
                allowed_trace_kinds=("residue",),
            ),
        ),
        "roles": (
            RoleDef(
                key="maid",
                record_kinds=("ledger",),
                motive_types=("debt",),
                names=(Entry(text="Maud", pronoun="she", proper=True),),
                traits=("quiet",),
            ),
        ),
        "record_kinds": ("ledger",),
        "slot_defs": (SlotDef(key="dawn", at="at dawn", during="during the dawn watch"),),
        "location_defs": (
            LocationDef(
                key="study",
                names=(Entry(text="Study", article="the"),),
                descriptions=("{^place} smells of ink.",),
            ),
        ),
        "record_defs": (
            RecordDef(
                key="ledger",
                subject="suspect",
                medium="written",
                presence=("The ledger lists {who} {time.at}.",),
            ),
        ),
        "method_defs": (
            MethodDef(
                key="poison",
                label="poisoned in the wine",
                aliases=("poison",),
                traces=(
                    TraceDef(
                        kind="residue",
                        location_kinds=("study",),
                        templates=("A film clings to a cup {place.in}.",),
                    ),
                ),
            ),
        ),
        "motive_defs": (
            MotiveDef(
                key="debt",
                label="to cover a gambling debt",
                aliases=("debt",),
                secrets=("{^who.poss} purse is empty.",),
            ),
        ),
        "families": (
            FamilyDef(
                id="alibi", kind="alibi", claim_slots=("who",), variants=("{^who} was seen.",)
            ),
        ),
    }
    fields.update(changes)
    return Pack(**fields)
