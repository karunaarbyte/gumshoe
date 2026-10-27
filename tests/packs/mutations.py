"""Table of deliberate pack defects: each names its catalogue code and the full expected set."""

from collections.abc import Callable
from dataclasses import dataclass

from gumshoe.cases.packs.catalogue import PACK_CATALOGUE

Edit = Callable[[str], str]


@dataclass(frozen=True)
class PackMutation:
    code: str
    apply: Edit
    expected: frozenset[str]  # the FULL expected code set (target plus declared cascade)


MUTATIONS: dict[str, PackMutation] = {}


def replace(old: str, new: str) -> Edit:
    def apply(text: str) -> str:
        assert old in text, f"not in the base pack: {old!r}"
        return text.replace(old, new, 1)

    return apply


def append(extra: str) -> Edit:
    return lambda text: text + "\n" + extra


def chain(*edits: Edit) -> Edit:
    def apply(text: str) -> str:
        for edit in edits:
            text = edit(text)
        return text

    return apply


def mutation(code: str, apply: Edit, expected: set[str] | None = None) -> None:
    assert code in PACK_CATALOGUE, f"unknown code {code}"
    assert code not in MUTATIONS, f"duplicate mutation for {code}"
    MUTATIONS[code] = PackMutation(code, apply, frozenset(expected or {code}))


# a new motive needs hints, like the three of the base pack
_HINTS = (
    'hints = [\n  "{^who} watched every coin go by with a thoughtful look.",\n'
    '  "{^who} sold small things from a room one by one.",\n'
    '  "{^who} looked away whenever dice were mentioned.",\n]\n'
)


# ---- stage 1: schema ------------------------------------------------------------------------

mutation("TOML_SYNTAX", append("[[[bad"))
mutation("UNKNOWN_KEY", replace('kind = "wound"\n', 'kind = "wound"\ncolour = "red"\n'))
mutation("WRONG_TYPE", replace("max_suspects = 3", 'max_suspects = "three"'))
mutation("MISSING_FIELD", replace('label = "stabbed with a dagger"\n', ""))

# ---- stage 2: closed references (they stop the later stages) ---------------------------------

mutation(
    "UNKNOWN_LOCATION_KIND", replace('location_kinds = ["study"]', 'location_kinds = ["crypt"]')
)
mutation(
    "UNKNOWN_RECORD_KIND",
    replace('record_kinds = ["ledger"]', 'record_kinds = ["diary"]'),
)
mutation(
    "UNKNOWN_TRACE_KIND",
    replace(
        'allowed_trace_kinds = ["fibre", "residue", "wound"]',
        'allowed_trace_kinds = ["fibre", "residue", "blood"]',
    ),
)
mutation(
    "UNKNOWN_METHOD",
    replace(
        'allowed_methods = ["dagger", "poison", "rope"]',
        'allowed_methods = ["dagger", "poison", "axe"]',
    ),
)
mutation(
    "UNKNOWN_MOTIVE_TYPE",
    replace(
        'motive_types = ["debt", "inheritance", "jealousy"]',
        'motive_types = ["debt", "inheritance", "greed"]',
    ),
)
mutation("DUPLICATE_KEY", replace('key = "noon"', 'key = "dawn"'))


# ---- stage 3: templates ----------------------------------------------------------------------

_STUDY = "{^place} smells of ink and cold ash."
mutation("UNKNOWN_PLACEHOLDER", replace(_STUDY, "{^plce} smells of ink and cold ash."))
mutation("UNRESOLVED_BRACE", replace("{^place} is damp, low", "{^place} is {damp, low"))
mutation("DOUBLED_WORD", replace("of ink and cold ash.", "of ink and cold cold ash."))
mutation("DOUBLE_SPACE", replace("of ink and cold ash.", "of ink  and cold ash."))
mutation("ARTICLE_MISMATCH", replace("of ink and cold ash.", "of ink and a ash."))
mutation("MID_SENTENCE_CAPITAL", replace("smells of ink and", "smells of Ink and"))
mutation(
    "TOO_FEW_VARIANTS",
    replace('  "{^who} could not have gone far, being {place.in} at the time.",\n', ""),
)
mutation(
    "CLAIM_SLOT_MISSING",
    replace(
        "{^who} was seen {place.in} when the bell rang.", "{^who} was seen when the bell rang."
    ),
)


# ---- stage 4: hygiene and leak rules ---------------------------------------------------------

mutation(
    "LABEL_TOKEN_LEAK",
    replace('traits = ["quiet and watchful"]', 'traits = ["quiet and handy with a dagger"]'),
)
mutation(
    "SECRET_REUSES_LABEL",
    replace(
        "{^who.poss} purse has stood empty since the autumn fair.",
        "{^who.poss} gambling habit is known to the whole kitchen.",
    ),
)
mutation(
    "TRACE_COUNT_SKEW",
    replace('  "A frayed length of hemp was found coiled up {place.in} near the door.",\n', ""),
    {"TRACE_COUNT_SKEW", "TRACE_SHAPE_SKEW"},  # the spare absent text has no template to mirror
)
# the longer template also pulls the mean of the templates away from the mean of the absent texts
mutation(
    "TRACE_LENGTH_SKEW",
    replace(
        "in a long arc.",
        "in a long arc. It was the kind of mark that takes a long and careful look to notice.",
    ),
    {"TRACE_LENGTH_SKEW", "TEXT_LENGTH_SKEW", "TRACE_SHAPE_SKEW"},
)

# "stabbing" stems to the dagger's distinctive token "stab"
mutation("ROLE_TOKEN_COLLISION", replace('noun = "maid"', 'noun = "stabbing"'))

# ---- stage 5: plausibility (a failure here also skips stages 6 and 7) ------------------------

mutation("ROLE_NO_NOUN", replace('noun = "maid"\n', ""))
mutation("RECORD_NO_NAME", replace('names = [{ text = "ledger", article = "the" }]\n', ""))
mutation(
    "RECORD_NO_LOCATION_KIND",
    replace('location_kinds = ["cellar", "garden", "study"]', "location_kinds = []"),
)
mutation("ROLE_NO_RECORD_KIND", replace('record_kinds = ["ledger"]', "record_kinds = []"))
mutation(
    "ROLE_NO_SUSPECT_RECORD",
    replace('record_kinds = ["ledger"]', 'record_kinds = ["gate_log"]'),
)
mutation(
    "ROLE_TOO_FEW_MOTIVES",
    replace(
        'motive_types = ["debt", "inheritance", "jealousy"]',
        'motive_types = ["debt", "inheritance"]',
    ),
)
mutation(
    "MOTIVE_UNREACHABLE",
    append(
        '[motive_defs.greed]\nlabel = "from greed"\naliases = ["greedy"]\nsecrets = []\n' + _HINTS
    ),
)
mutation("SCENE_NO_CRIME_LOCATION", replace('location_kinds = ["study"]', "location_kinds = []"))
mutation(
    "SCENE_MANY_CRIME_LOCATIONS",
    replace(
        '[scene_types.garden_murder]\nlocation_kinds = ["garden"]',
        '[scene_types.garden_murder]\nlocation_kinds = ["garden", "study"]',
    ),
)
mutation(
    "METHOD_TOO_RARE",
    chain(
        replace(
            '[scene_types.garden_murder]\nlocation_kinds = ["garden"]\n'
            'allowed_methods = ["dagger", "poison", "rope"]',
            '[scene_types.garden_murder]\nlocation_kinds = ["garden"]\n'
            'allowed_methods = ["dagger", "poison"]',
        ),
        replace(
            '[scene_types.cellar_murder]\nlocation_kinds = ["cellar"]\n'
            'allowed_methods = ["dagger", "poison", "rope"]',
            '[scene_types.cellar_murder]\nlocation_kinds = ["cellar"]\n'
            'allowed_methods = ["dagger", "poison"]',
        ),
    ),
)
mutation(
    "SCENE_METHOD_IMPOSSIBLE",
    replace(
        '[scene_types.garden_murder]\nlocation_kinds = ["garden"]\n'
        'allowed_methods = ["dagger", "poison", "rope"]\n'
        'allowed_trace_kinds = ["fibre", "residue", "wound"]',
        '[scene_types.garden_murder]\nlocation_kinds = ["garden"]\n'
        'allowed_methods = ["dagger", "poison", "rope"]\n'
        'allowed_trace_kinds = ["fibre", "residue"]',
    ),
)
mutation(
    "SLOT_DEFS_TOO_FEW",
    replace(
        '[[slot_defs]]\nkey = "night"\nat = "at midnight"\nduring = "during the night watch"\n',
        "",
    ),
)

# ---- stage 6: capacity and presets -----------------------------------------------------------

mutation("PRESET_UNSUPPORTED", replace('presets = ["tiny"]', 'presets = ["tiny", "huge"]'))
mutation("PRESET_NOT_MONOTONE", replace('presets = ["tiny"]', 'presets = ["short", "standard"]'))


mutation("CAPACITY_EXCEEDS_POOL", replace("max_suspects = 3", "max_suspects = 4"))


def _every(old: str, new: str) -> Edit:
    def apply(text: str) -> str:
        assert old in text, f"not in the base pack: {old!r}"
        return text.replace(old, new)

    return apply


mutation(
    "LOCATION_KINDS_TOO_FEW",
    chain(
        replace(
            '[location_defs.cellar]\nnames = [{ text = "Cellar", article = "the" }]\n'
            'descriptions = ["{^place} is damp, low and lined with dusty racks."]\n',
            "",
        ),
        replace('location_kinds = ["cellar"]\npresence', 'location_kinds = ["garden"]\npresence'),
        _every(
            'location_kinds = ["cellar", "garden", "study"]', 'location_kinds = ["garden", "study"]'
        ),
        replace(
            '[scene_types.cellar_murder]\nlocation_kinds = ["cellar"]\n'
            'allowed_methods = ["dagger", "poison", "rope"]\n'
            'allowed_trace_kinds = ["fibre", "residue", "wound"]\n',
            "",
        ),
        replace("max_locations = 3", "max_locations = 2"),
    ),
    {"LOCATION_KINDS_TOO_FEW", "PRESET_UNSUPPORTED"},
)

# ---- stage 7: motive matching ----------------------------------------------------------------

_QUAD = chain(
    replace("max_suspects = 3", "max_suspects = 4"),
    replace('presets = ["tiny"]', 'presets = ["quad"]'),
    append(
        '[motive_defs.greed]\nlabel = "from greed"\naliases = ["greedy"]\n'
        'secrets = ["{^who} counts every coin twice."]\n' + _HINTS
    ),
    append(
        '[roles.groom]\nnames = [{ text = "Wat", pronoun = "he", proper = true }]\nnoun = "groom"\n'
        'style = "easygoing and shy"\n'
        'traits = ["gentle with horses"]\nrecord_kinds = ["ledger"]\n'
        'motive_types = ["debt", "greed", "inheritance"]\n'
    ),
)
_PAGE = append(
    '[roles.page]\nnames = [{ text = "Piers", pronoun = "he", proper = true }]\nnoun = "page"\n'
    'style = "quick and eager"\n'
    'traits = ["fast on his feet"]\nrecord_kinds = ["ledger"]\n'
    'motive_types = ["debt", "inheritance", "jealousy"]\n'
)

# a groom is the only role that can take "greed", so in the roster maid+steward+cook+groom the
# groom always gets it: predictable
mutation("MOTIVE_TOO_PREDICTABLE", _QUAD)
# four roles share three motive types: the roster maid+steward+cook+page has no matching, and
# the rosters with the groom are as predictable as above
mutation(
    "NO_PERFECT_MATCHING",
    chain(_QUAD, _PAGE),
    {"NO_PERFECT_MATCHING", "MOTIVE_TOO_PREDICTABLE"},
)

# ---- stage 8: skin inputs ----------------------------------------------------------------------

mutation(
    "MISSING_FAMILY",
    replace('id = "intro"\nkind = "intro"', 'id = "intro"\nkind = "scene"'),
)
# the key family takes the kind of the intro family, so the key kind is missing too
mutation(
    "DUPLICATE_FAMILY_KIND",
    replace('id = "key"\nkind = "key"', 'id = "key"\nkind = "intro"'),
    {"DUPLICATE_FAMILY_KIND", "MISSING_FAMILY"},
)
mutation(
    "TOO_FEW_TEXTS",
    replace('[[victims]]\ntext = "Lord Wulfric"\npronoun = "he"\nproper = true\n', ""),
)
mutation("ENTRY_INCOMPLETE", replace('style = "quick and chatty; passes on household talk"\n', ""))
mutation(
    "TEXT_COUNT_SKEW",
    replace(
        '  "A belt hook {place.in} swung empty on its nail.",\n',
        '  "A belt hook {place.in} swung empty on its nail.",\n'
        '  "A rag {place.in} was oiled and folded small.",\n',
    ),
)
_LONG = (
    "The floor {place.in} was scrubbed pale, with every board smooth and every crack filled "
    "with fresh lime, so that a visitor could have eaten a meal off it."
)
mutation(
    "TEXT_LENGTH_SKEW",
    replace("Clean boards {place.in} were swept bare across the floor in a line.", _LONG),
    {"TEXT_LENGTH_SKEW", "TRACE_SHAPE_SKEW"},  # a longer text is also a different shape
)
# the same words, the place moved from the middle of the sentence to its end
mutation(
    "TRACE_SHAPE_SKEW",
    replace(
        "Tidy threads wound upon a hook {place.in} came from something ordinary.",
        "Tidy threads wound upon a hook came from something ordinary {place.in}.",
    ),
)
mutation(
    "PAIR_COUNT_SKEW",
    replace(
        '  "{^record} mentioned the cap of {who}, crushed with a bent brim.",\n',
        '  "{^record} mentioned the cap of {who}, crushed with a bent brim.",\n'
        '  "{^record} noted the hat of {who}, crushed with a bent brim.",\n',
    ),
)
_LONG_PROOF = (
    "{^record} noted the cloak of {who}, damp and torn at the hem, with a long rip running up "
    "the back and thorns caught in every fold of the cloth."
)
mutation(
    "PAIR_LENGTH_SKEW",
    replace("{^record} noted the cloak of {who}, damp and torn at the hem.", _LONG_PROOF),
)
# "wine" is a token of the poison method's alias "laced wine"
mutation("BAD_SMALLTALK_WORD", replace('"warm", "weather",', '"warm", "wine",'))
