"""Pure text lints for pack templates. Rendering uses fixed sample values (lint only), so a
bad template is found without a generator."""

import re
from collections.abc import Iterator

from gumshoe.cases.core.text import normalise
from gumshoe.cases.model.pack import Pack

KNOWN_PLACEHOLDERS = frozenset(
    {
        "who",
        "who.subj",
        "who.poss",
        "item.a",
        "item.the",
        "place",
        "place.in",
        "time.phrase",
        "time.at",
        "time.during",
    }
)
_PLACEHOLDER = re.compile(r"\{(\^?)([^{}]*)\}")

# Two samples keep the check bounded and deterministic: a vowel-initial and a consonant-initial one.
SAMPLES: tuple[dict[str, str], ...] = (
    {
        "who": "Edmund",
        "who.subj": "he",
        "who.poss": "his",
        "item.a": "a lantern",
        "item.the": "the lantern",
        "place": "the Chapel",
        "place.in": "in the Chapel",
        "time.phrase": "at vespers",
        "time.at": "at vespers",
        "time.during": "during vespers",
    },
    {
        "who": "Maud",
        "who.subj": "she",
        "who.poss": "her",
        "item.a": "an axe",
        "item.the": "the axe",
        "place": "the old keep",
        "place.in": "in the old keep",
        "time.phrase": "during the feast",
        "time.at": "at the feast",
        "time.during": "during the feast",
    },
)


def placeholders(text: str) -> list[str]:
    return [m.group(2) for m in _PLACEHOLDER.finditer(text)]


def render(text: str, sample: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        value = sample.get(match.group(2), "")
        return value[:1].upper() + value[1:] if match.group(1) and value else value

    return _PLACEHOLDER.sub(substitute, text)


def stray_brace(text: str) -> bool:
    rest = _PLACEHOLDER.sub("", text)
    return "{" in rest or "}" in rest


def doubled_word(text: str) -> str | None:
    words = normalise(text).split()
    return next((a for a, b in zip(words, words[1:], strict=False) if a == b), None)


def double_space(text: str) -> bool:
    return "  " in text


def article_mismatch(text: str) -> str | None:
    words = normalise(text).split()
    for first, second in zip(words, words[1:], strict=False):
        if first == "a" and second[0] in "aeiou":
            return f"{first} {second}"
        if first == "an" and second[0].isalpha() and second[0] not in "aeiou":
            return f"{first} {second}"
    return None


def mid_sentence_capital(text: str) -> str | None:
    """A capitalised literal word inside a sentence (names must come from placeholders)."""
    at_start = True
    for word in _PLACEHOLDER.sub(" ", text).split():
        bare = word.lstrip("\"'(")
        if bare and bare[0].isupper() and not at_start and bare != "I":
            return bare.rstrip(".,;:!?")
        at_start = word.endswith((".", "!", "?"))
    return None


def template_items(pack: Pack) -> Iterator[tuple[str, str]]:
    """Every templated text in the pack with its key path."""
    for family in pack.families:
        for i, text in enumerate(family.variants):
            yield f"families.{family.id}.variants[{i}]", text
    for location in pack.location_defs:
        for i, text in enumerate(location.descriptions):
            yield f"location_defs.{location.key}.descriptions[{i}]", text
    for record in pack.record_defs:
        for i, text in enumerate(record.presence):
            yield f"record_defs.{record.key}.presence[{i}]", text
    for method in pack.method_defs:
        for trace in method.traces:
            for i, text in enumerate(trace.templates):
                yield f"method_defs.{method.key}.traces[{trace.kind}].templates[{i}]", text
    for motive in pack.motive_defs:
        for i, text in enumerate(motive.secrets):
            yield f"motive_defs.{motive.key}.secrets[{i}]", text
