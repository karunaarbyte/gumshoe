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
from gumshoe.cases.model.spec import PresetDef, SizeRange
from tests.cases.fixtures import LIMITS

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
                id="alibi",
                kind="alibi",
                claim_slots=("who",),
                variants=tuple(f"{{^who}} was seen on day{i}." for i in range(5)),
            ),
        ),
    }
    fields.update(changes)
    return Pack(**fields)


def _preset(name: str, suspects: int, locations: int) -> PresetDef:
    return PresetDef(
        name=name,
        suspects=SizeRange(min=suspects, max=suspects),
        methods=SizeRange(min=3, max=3),
        locations=SizeRange(min=locations, max=locations),
        record_kinds=SizeRange(min=2, max=2),
        slots=4,
        limits=LIMITS,
    )


# "short" then "standard" shrink the locations on purpose, for the monotonicity test
TEST_PRESETS = {
    "tiny": _preset("tiny", 3, 3),
    "short": _preset("short", 3, 3),
    "standard": _preset("standard", 3, 2),
    "quad": _preset("quad", 4, 3),
}

BASE_TOML = """\
[meta]
id = "tiny"
skeleton_rev = 1
skin_rev = 1
slots = 4
presets = ["tiny"]

[capacity]
max_suspects = 3
max_locations = 3
max_methods = 3
max_record_kinds = 2

[[slot_defs]]
key = "dawn"
at = "at dawn"
during = "during the dawn watch"

[[slot_defs]]
key = "noon"
at = "at noon"
during = "during the midday meal"

[[slot_defs]]
key = "dusk"
at = "at dusk"
during = "during the evening bell"

[[slot_defs]]
key = "night"
at = "at midnight"
during = "during the night watch"

[location_defs.study]
names = [{ text = "Study", article = "the" }]
descriptions = ["{^place} smells of ink and cold ash."]

[location_defs.garden]
names = [{ text = "Garden", article = "the" }]
descriptions = ["{^place} is thick with wet roses and unpruned hedges."]

[location_defs.cellar]
names = [{ text = "Cellar", article = "the" }]
descriptions = ["{^place} is damp, low and lined with dusty racks."]

[record_defs.gate_log]
subject = "location"
medium = "written"
presence = ["The gate log shows {who} {time.at}."]

[record_defs.ledger]
subject = "suspect"
medium = "written"
presence = ["The ledger lists {who} {time.at}."]

[method_defs.dagger]
label = "stabbed with a dagger"
aliases = ["knife", "blade"]
[[method_defs.dagger.traces]]
kind = "wound"
location_kinds = ["cellar", "garden", "study"]
templates = [
  "A narrow cut in the clothing {place.in} shows where the blow fell.",
  "Dark stains {place.in} were smeared across the floor in a long arc.",
]

[method_defs.poison]
label = "poisoned in the wine"
aliases = ["poison", "laced wine"]
[[method_defs.poison.traces]]
kind = "residue"
location_kinds = ["cellar", "garden", "study"]
templates = [
  "A bitter film clings to a cup {place.in}, left untouched until now.",
  "Pale crust has dried along the rim of a cup {place.in} this week.",
]

[method_defs.rope]
label = "strangled with a rope"
aliases = ["rope", "garrote"]
[[method_defs.rope.traces]]
kind = "fibre"
location_kinds = ["cellar", "garden", "study"]
templates = [
  "Coarse threads caught on a hook {place.in} came from something twisted.",
  "A frayed length of hemp was found coiled up {place.in} near the door.",
]

[motive_defs.debt]
label = "to cover a gambling debt"
aliases = ["debt", "money owed"]
secrets = ["{^who.poss} purse has stood empty since the autumn fair."]

[motive_defs.inheritance]
label = "to claim an inheritance"
aliases = ["inherit", "legacy"]
secrets = ["{^who} has read the old will many times over."]

[motive_defs.jealousy]
label = "out of jealousy"
aliases = ["jealous", "envy"]
secrets = ["{^who} cannot bear to watch the master's favourites."]

[roles.maid]
names = [{ text = "Maud", pronoun = "she", proper = true }]
traits = ["quiet and watchful"]
record_kinds = ["ledger"]
motive_types = ["debt", "inheritance", "jealousy"]

[roles.steward]
names = [{ text = "Edmund", pronoun = "he", proper = true }]
traits = ["stern and exact"]
record_kinds = ["ledger"]
motive_types = ["debt", "inheritance", "jealousy"]

[roles.cook]
names = [{ text = "Hob", pronoun = "he", proper = true }]
traits = ["ruddy and quick to laugh"]
record_kinds = ["ledger"]
motive_types = ["debt", "inheritance", "jealousy"]

[scene_types.study_murder]
location_kinds = ["study"]
allowed_methods = ["dagger", "poison", "rope"]
allowed_trace_kinds = ["fibre", "residue", "wound"]

[scene_types.garden_murder]
location_kinds = ["garden"]
allowed_methods = ["dagger", "poison", "rope"]
allowed_trace_kinds = ["fibre", "residue", "wound"]

[[families]]
id = "alibi"
kind = "alibi"
claim_slots = ["who", "place.in"]
variants = [
  "{^who} was seen {place.in} when the bell rang.",
  "Several people place {who} {place.in} as the hour struck.",
  "A servant swears {who} never left {place.in}.",
  "The porter vouches that {who} stayed {place.in} all evening.",
  "{^who} could not have gone far, being {place.in} at the time.",
]

[[families]]
id = "presence_record"
kind = "presence"
claim_slots = ["who", "time.at"]
variants = [
  "The register shows {who} {time.at}.",
  "{^who} signed the book {time.at}.",
  "An entry puts {who} on the premises {time.at}.",
  "The clerk noted {who} {time.at}.",
  "Records place {who} nearby {time.at}.",
]
"""
