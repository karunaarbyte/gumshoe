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
