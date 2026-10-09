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


def scenes(
    count: int, methods: tuple[str, ...] = ("dagger", "poison", "rope")
) -> tuple[SceneType, ...]:
    """`count` scene types that each allow every given method, for capacity tests."""
    return tuple(
        SceneType(
            key=f"scene{i}",
            location_kinds=("study",),
            allowed_methods=methods,
            allowed_trace_kinds=("residue",),
        )
        for i in range(count)
    )


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
                noun="maid",
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
            LocationDef(
                key="garden",
                names=(Entry(text="Garden", article="the"),),
                descriptions=("{^place} is wet.",),
            ),
        ),
        "record_defs": (
            RecordDef(
                key="ledger",
                subject="suspect",
                medium="written",
                presence=("The ledger lists {who} {time.at}.",),
                names=(Entry(text="ledger", article="the"),),
                location_kinds=("garden", "study"),
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


def preset(name: str, suspects: int, locations: int) -> PresetDef:
    return PresetDef(
        name=name,
        suspects=SizeRange(min=suspects, max=suspects),
        methods=SizeRange(min=3, max=3),
        locations=SizeRange(min=locations, max=locations),
        record_kinds=SizeRange(min=2, max=2),
        slots=4,
        opportunity=min(1, suspects - 1),
        limits=LIMITS,
    )


# "short" then "standard" shrink the locations on purpose, for the monotonicity test
TEST_PRESETS = {
    "tiny": preset("tiny", 3, 3),
    "short": preset("short", 3, 3),
    "standard": preset("standard", 3, 2),
    "quad": preset("quad", 4, 3),
}

BASE_TOML_NO_SKIN = """\
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
names = [{ text = "gate log", article = "the" }]
location_kinds = ["cellar"]
presence = ["The gate log shows {who} {time.at}."]

[record_defs.ledger]
subject = "suspect"
medium = "written"
names = [{ text = "ledger", article = "the" }]
location_kinds = ["cellar", "garden", "study"]
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
noun = "maid"
traits = ["quiet and watchful"]
record_kinds = ["ledger"]
motive_types = ["debt", "inheritance", "jealousy"]

[roles.steward]
names = [{ text = "Edmund", pronoun = "he", proper = true }]
noun = "steward"
traits = ["stern and exact"]
record_kinds = ["ledger"]
motive_types = ["debt", "inheritance", "jealousy"]

[roles.cook]
names = [{ text = "Hob", pronoun = "he", proper = true }]
noun = "cook"
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

[scene_types.cellar_murder]
location_kinds = ["cellar"]
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


# What stage 8 asks of a pack, added to the base pack. Edits are (old, new) pairs applied once each,
# in order; every `old` is a unique anchor in `BASE_TOML_NO_SKIN`.
_FAMILIES = """
[[families]]
id = "physical_proof"
kind = "physical_proof"
claim_slots = ["who", "record"]
variants = [
  "{^record} noted the cloak of {who}, damp and torn at the hem.",
  "An entry in {record} described the boots of {who}: caked with mud along the soles.",
  "{^record} listed the gloves of {who} as scuffed and creased across the palms.",
  "{^record} recorded that the belt of {who} was smeared and its buckle bent.",
  "{^record} mentioned the cap of {who}, crushed with a bent brim.",
]

[[families]]
id = "physical_clear"
kind = "physical_clear"
claim_slots = ["who", "record"]
variants = [
  "{^record} noted the cloak of {who}, dry and whole at the hem.",
  "An entry in {record} described the boots of {who}: clean and polished along the soles.",
  "{^record} listed the gloves of {who} as smooth and supple across the palms.",
  "{^record} recorded that the belt of {who} was clean and its buckle bright.",
  "{^record} mentioned the cap of {who}, neat with a straight brim.",
]

[[families]]
id = "key"
kind = "key"
claim_slots = ["who"]
variants = [
  "A scrap of paper with the name of {who} on it was found tucked into a book.",
  "{^who} was named in a note that had been left on a table.",
  "A servant remembered that {who} had asked for a word with the lord.",
  "The name of {who} was scratched on a slate by the pantry door.",
  "A message addressed to {who} was waiting unopened on a shelf.",
]

[[families]]
id = "contradiction"
kind = "contradiction"
claim_slots = ["who", "place.in", "time.at", "record"]
variants = [
  "But {record} put {who} {place.in} {time.at}.",
  "Yet an entry in {record} placed {who} {place.in} {time.at}.",
  "However, {record} listed {who} {place.in} {time.at}.",
  "Against that, {record} showed {who} {place.in} {time.at}.",
  "Still, {record} named {who} {place.in} {time.at}.",
]

[[families]]
id = "intro"
kind = "intro"
claim_slots = ["victim", "place.in", "time.during"]
variants = [
  "{^victim} was found dead {place.in}, and the crime was done {time.during}.",
  "The household woke to the news that {victim} had been killed {place.in} {time.during}.",
  "{^victim} died {place.in} {time.during}, and the whole castle was shaken.",
  "Word spread that {victim} had been murdered {place.in} {time.during}.",
  "{^victim} was killed {place.in} {time.during}, and the gates were closed at once.",
]
""" + "".join(
    f'\n[[victims]]\ntext = "Lord {name}"\npronoun = "he"\nproper = true\n'
    for name in ("Aldric", "Godwin", "Osmund", "Baldric", "Ranulf", "Wulfric")
)

_SKIN_EDITS: tuple[tuple[str, str], ...] = (
    (
        'presets = ["tiny"]\n\n[capacity]',
        'presets = ["tiny"]\nsmalltalk_allow = [\n'
        '  "ale", "bread", "breakfast", "cheers", "cold", "dinner", "evening", "fire", "goodbye",\n'
        '  "hello", "morning", "pardon", "please", "rain", "soup", "sunshine", "supper",\n'
        '  "thanks", "warm", "weather",\n]\n\n[capacity]',
    ),
    (
        'presence = ["The gate log shows {who} {time.at}."]',
        'presence = ["The gate log shows {who} {time.at}."]\nentries = [\n'
        '  "{^record} lay open on a slanted desk.",\n'
        '  "{^record} was kept in a leather binding.",\n'
        '  "Several hands had written in {record}.",\n]',
    ),
    (
        '  "Dark stains {place.in} were smeared across the floor in a long arc.",\n]',
        '  "Dark stains {place.in} were smeared across the floor in a long arc.",\n]\nabsent = [\n'
        '  "The clothing {place.in} hung whole, and the floor was swept clean.",\n'
        '  "The floor {place.in} was scrubbed pale, with every board smooth.",\n]',
    ),
    (
        '  "Pale crust has dried along the rim of a cup {place.in} this week.",\n]',
        '  "Pale crust has dried along the rim of a cup {place.in} this week.",\n]\nabsent = [\n'
        '  "A cup {place.in} stood clean and dry on a shelf, left alone for days.",\n'
        '  "The rim of a cup {place.in} was smooth and bright, wiped this week.",\n]',
    ),
    (
        '  "A frayed length of hemp was found coiled up {place.in} near the door.",\n]',
        '  "A frayed length of hemp was found coiled up {place.in} near the door.",\n]\n'
        "absent = [\n"
        '  "A hook {place.in} hung clean, and a length of hemp lay straight near it.",\n'
        '  "The threads {place.in} were firm and tidy, wound up on a clean reel.",\n]',
    ),
    (
        'aliases = ["knife", "blade"]\n',
        'aliases = ["knife", "blade"]\nclues = [\n'
        '  "A whetstone {place.in} was still wet, with fresh grey streaks.",\n'
        '  "A strip of oiled cloth {place.in} smelled of steel and lay in a knot.",\n'
        '  "A belt hook {place.in} swung empty on its nail.",\n]\n',
    ),
    (
        'aliases = ["poison", "laced wine"]\n',
        'aliases = ["poison", "laced wine"]\nclues = [\n'
        '  "A small stoppered phial lay {place.in}, rinsed and set on its side.",\n'
        '  "A servant said the casks {place.in} had been tapped a day early.",\n'
        '  "A damp cloth {place.in} smelled sharp and sour.",\n]\n',
    ),
    (
        'aliases = ["rope", "garrote"]\n',
        'aliases = ["rope", "garrote"]\nclues = [\n'
        '  "A length of spare hemp had been cut from a coil {place.in}.",\n'
        '  "A knot of heavy twine lay {place.in}, tied by a practised hand.",\n'
        '  "A stable boy said a coil had gone from its hook {place.in}.",\n]\n',
    ),
    (
        'secrets = ["{^who.poss} purse has stood empty since the autumn fair."]',
        'secrets = ["{^who.poss} purse has stood empty since the autumn fair."]\nhints = [\n'
        '  "{^who} avoided the pedlars who came to the gate.",\n'
        '  "{^who} sold small things from {who.poss} room one by one.",\n'
        '  "{^who} looked away whenever dice were mentioned.",\n]',
    ),
    (
        'secrets = ["{^who} has read the old will many times over."]',
        'secrets = ["{^who} has read the old will many times over."]\nhints = [\n'
        '  "{^who} knew the names in the lord\'s family tree by heart.",\n'
        '  "{^who} asked often after the lord\'s health with a frown.",\n'
        '  "{^who} kept a close count of the lord\'s years.",\n]',
    ),
    (
        'secrets = ["{^who} cannot bear to watch the master\'s favourites."]',
        'secrets = ["{^who} cannot bear to watch the master\'s favourites."]\nhints = [\n'
        '  "{^who} fell silent whenever the favourite was praised.",\n'
        '  "{^who} sat close to the favourite at meals and watched each gesture.",\n'
        '  "{^who} found fault with the dress of the favourite.",\n]',
    ),
    (
        'noun = "maid"\ntraits',
        'noun = "maid"\nstyle = "quick and chatty; passes on household talk"\ntraits',
    ),
    (
        'noun = "steward"\ntraits',
        'noun = "steward"\nstyle = "stiff and proud; speaks like someone used to giving orders"\n'
        "traits",
    ),
    (
        'noun = "cook"\ntraits',
        'noun = "cook"\nstyle = "blunt and warm; grumbles about the long hours"\ntraits',
    ),
    (
        '  "Records place {who} nearby {time.at}.",\n]\n',
        '  "Records place {who} nearby {time.at}.",\n]\n' + _FAMILIES,
    ),
)


def skin_ready(text: str) -> str:
    """The base pack with every text stage 8 asks for (it is clean through stages 1 to 8)."""
    for old, new in _SKIN_EDITS:
        assert old in text, f"not in the base pack: {old!r}"
        text = text.replace(old, new, 1)
    return text


SKIN_BASE_TOML = skin_ready(BASE_TOML_NO_SKIN)
BASE_TOML = SKIN_BASE_TOML
