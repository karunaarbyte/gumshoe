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
)
mutation(
    "TRACE_LENGTH_SKEW",
    replace(
        "in a long arc.",
        "in a long arc. It was the kind of mark that takes a long and careful look to notice.",
    ),
)
