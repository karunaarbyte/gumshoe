"""The case-level text checks the validator does not have: leaks, label against name, duplicate
sentences, claim fidelity and render hygiene. Pure: it reads the skinned case and the pack."""

from collections.abc import Iterator

from gumshoe.cases.core.labels import distinctive, token_set
from gumshoe.cases.core.text import normalise, tokens
from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.skin_catalogue import SkinIssue, make
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact
from gumshoe.cases.model.enums import FactKind, SourceKind
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.check.hygiene import candidate_tokens
from gumshoe.cases.packs.check.lint import (
    article_mismatch,
    double_space,
    doubled_word,
    phrase,
    stray_brace,
)

Text = tuple[str, str, frozenset[str]]  # path, text, the candidates the text touches


def _texts(case: Case) -> Iterator[Text]:
    """Every text of the case. A fact touches the candidates its effects name; nothing else
    (a contradiction, the intro, a name, a trait) touches any."""
    for f in case.facts:
        yield f"facts.{f.id}.text", f.text, frozenset(e.candidate for e in f.effects)
        if f.contradiction:
            yield f"facts.{f.id}.contradiction", f.contradiction, frozenset()
    yield "intro", case.intro, frozenset()
    for loc in case.locations:
        yield f"locations.{loc.id}.name", loc.name, frozenset()
        yield f"locations.{loc.id}.description", loc.description, frozenset()
    for s in case.suspects:
        yield f"suspects.{s.id}.display_name", s.display_name, frozenset()
        yield f"suspects.{s.id}.style", s.style, frozenset()
        for i, trait in enumerate(s.traits):
            yield f"suspects.{s.id}.traits[{i}]", trait, frozenset()


def _blank(case: Case) -> list[SkinIssue]:
    needed = [(f"facts.{f.id}.text", f.text) for f in case.facts]
    needed += [("intro", case.intro)]
    needed += [(f"locations.{x.id}.name", x.name) for x in case.locations]
    needed += [(f"locations.{x.id}.description", x.description) for x in case.locations]
    for s in case.suspects:
        needed += [(f"suspects.{s.id}.display_name", s.display_name)]
        needed += [(f"suspects.{s.id}.style", s.style)]
        needed += [(f"suspects.{s.id}.secret_text", s.secret_text)]
        needed += [(f"suspects.{s.id}.traits", " ".join(s.traits))]
    return [make("BLANK_TEXT", path) for path, text in needed if not text.strip()]


def _render(case: Case) -> list[SkinIssue]:
    out: list[SkinIssue] = []
    for path, text, _ in _texts(case):
        if "{" in text or "}" in text or stray_brace(text):
            out.append(make("BAD_RENDER", path, problem="a stray brace"))
        if double_space(text):
            out.append(make("BAD_RENDER", path, problem="two spaces in a row"))
        if (word := doubled_word(text)) is not None:
            out.append(make("BAD_RENDER", path, problem=f"the doubled word {word!r}"))
        if (clash := article_mismatch(text)) is not None:
            out.append(
                make("BAD_RENDER", path, problem=f"an article that does not fit ({clash!r})")
            )
    return out


def _duplicates(case: Case) -> list[SkinIssue]:
    seen: dict[str, str] = {}
    out: list[SkinIssue] = []
    sentences = [(p, t) for p, t, _ in _texts(case) if p.startswith("facts.") or p == "intro"]
    for path, text in sentences:
        key = normalise(text)
        if key and key in seen:
            out.append(make("DUPLICATE_SENTENCE", path, other=seen[key]))
        seen.setdefault(key, path)
    return out


def _has(text: str, value: str) -> bool:
    """Whether the value stands in the text as whole words ("the Keep" is not in "the Keeper")."""
    return f" {normalise(value)} " in f" {normalise(text)} "


def _expected(case: Case, pack: Pack, fact: Fact) -> list[tuple[str, str]]:
    """What the text of a fact must hold: (kind of value, the value as rendered)."""
    suspects = {s.id: s for s in case.suspects}
    places = {x.id: x for x in case.locations}

    def who(suspect_id: str | None) -> tuple[str, str]:
        suspect = suspects.get(suspect_id or "")
        if suspect is None:
            raise GenerationError(f"fact {fact.id} names the suspect {suspect_id!r}")
        return "the person", phrase(slots.name_entry(pack, suspect))

    def where(location_id: str | None) -> tuple[str, str]:
        location = places.get(location_id or "")
        if location is None:
            raise GenerationError(f"fact {fact.id} names the place {location_id!r}")
        return "the place", phrase(slots.place_entry(pack, location))

    if fact.claim is not None:
        return [
            who(fact.claim.actor),
            where(fact.claim.place),
            ("the time", slots.slot_time(pack, fact.claim.slot)["time.at"]),
        ]
    if fact.kind in (FactKind.TRACE, FactKind.ABSENT_TRACE) or (
        fact.kind is FactKind.CLUE and fact.source.kind is SourceKind.SEARCH and fact.effects
    ):
        return [where(fact.source.target)]
    if fact.kind in (FactKind.SECRET, FactKind.PHYSICAL):
        return [who(fact.source.subject)]
    if fact.kind is FactKind.MOTIVE_CLUE:
        return [who(fact.speaker)]
    if fact.kind is FactKind.CLUE and fact.source.kind is SourceKind.RECORD:
        return [("the record", slots.record_name(pack, fact.source.target)["record"])]
    if fact.kind is FactKind.CLUE:
        holder = next((s for s in case.suspects if fact.id in s.requires), None)
        return [who(holder.id if holder else None)]
    return []


def _claims(case: Case, pack: Pack) -> list[SkinIssue]:
    out: list[SkinIssue] = []
    facts = {f.id: f for f in case.facts}
    for f in case.facts:
        for what, value in _expected(case, pack, f) if f.text.strip() else []:
            if not _has(f.text, value):
                out.append(
                    make("CLAIM_VALUE_MISSING", f"facts.{f.id}.text", what=what, value=value)
                )
        if f.kind is not FactKind.LIE:
            continue
        exposer = facts.get(f.exposed_by[0]) if f.exposed_by else None
        if exposer is None or exposer.claim is None:
            continue
        true_place = _expected(case, pack, exposer)[1][1]
        if not f.contradiction or not _has(f.contradiction, true_place):
            out.append(
                make("CONTRADICTION_MISSING", f"facts.{f.id}.contradiction", value=true_place)
            )
    return out


def _label(case: Case) -> list[SkinIssue]:
    sets = {s.id: token_set(s.label) for s in case.suspects}
    out: list[SkinIssue] = []
    for s in case.suspects:
        own = distinctive(sets[s.id], [v for k, v in sets.items() if k != s.id])
        have = set(tokens(s.display_name))
        out += [
            make("LABEL_NOT_IN_NAME", f"suspects.{s.id}.display_name", token=t)
            for t in sorted(own - have)
        ]
    return out


def _candidates(case: Case, pack: Pack) -> dict[str, frozenset[str]]:
    """Id of each method and motive in the case to its distinctive label tokens across the whole
    pack (the pack check's tokens, so a word the pack allows is allowed here)."""
    owned = candidate_tokens(pack)
    out: dict[str, frozenset[str]] = {}
    for prefix, items in (("method", case.methods), ("motive", case.motives)):
        for c in items:
            out[c.id] = owned.get(f"{prefix}:{c.type}", frozenset())
    return out


def _leaks(case: Case, pack: Pack) -> list[SkinIssue]:
    candidates = _candidates(case, pack)
    out: list[SkinIssue] = []
    for path, text, touched in _texts(case):
        have = set(tokens(text))
        for cid, own in candidates.items():
            if cid in touched:
                continue
            out += [make("LEAK_TOKEN", path, token=t, candidate=cid) for t in sorted(own & have)]
    return out


def lint(case: Case, pack: Pack) -> tuple[SkinIssue, ...]:
    """Every problem in the case's text, in a fixed order."""
    found = [
        *_blank(case),
        *_render(case),
        *_duplicates(case),
        *_claims(case, pack),
        *_label(case),
        *_leaks(case, pack),
    ]
    return tuple(sorted(found, key=lambda i: (i.code, i.path, i.message)))
