"""Shared by the skin tests: generated cases (cached) and what each fact may render to."""

from functools import cache

from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.pipeline import run_pipeline
from gumshoe.cases.generate.skin import template_skin
from gumshoe.cases.generate.skin_lint import lint as skin_lint
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind, SourceKind
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.check.lint import render
from tests.generate.helpers import castle


@cache
def the_castle() -> Pack:
    return castle()


def skinned(pack: Pack, seed: int, preset: str) -> Case:
    """The case for a seed with the template skin and the text lint, whatever `generate` does."""
    case, _ = run_pipeline(GenContext.of(pack, seed, preset), skin=template_skin, lint=skin_lint)
    return case


@cache
def made(seed: int, preset: str) -> Case:
    return skinned(the_castle(), seed, preset)


def _family(pack: Pack, *kinds: str) -> list[str]:
    return [v for f in pack.families if f.kind in kinds for v in f.variants]


def rendered(case: Case, pack: Pack, fact: Fact) -> list[str]:
    """Every text the fact may have, in the order of its list of variants, rendered with the
    fact's values. This is a second description of the contract table in the skin spec (2c.1b
    section 3)."""
    people = {s.id: s for s in case.suspects}
    places = {x.id: x for x in case.locations}
    methods = {m.id: m.type for m in case.methods}
    motives = {v.id: v.type for v in case.motives}

    def who(suspect_id: str | None) -> dict[str, str]:
        assert suspect_id is not None
        return slots.person(slots.name_entry(pack, people[suspect_id]))

    def where(location_id: str | None) -> dict[str, str]:
        assert location_id is not None
        return slots.place(slots.place_entry(pack, places[location_id]))

    record = (
        slots.record_name(pack, fact.source.target) if fact.source.kind is SourceKind.RECORD else {}
    )

    def effect(axis: Axis) -> tuple[str, EffectKind]:
        (found,) = [e for e in fact.effects if e.axis is axis]
        return found.candidate, found.kind

    def all_of(variants: list[str], values: dict[str, str]) -> list[str]:
        assert variants
        return [render(v, values) for v in variants]

    kind = fact.kind
    if kind is FactKind.SECRET:
        motive = next(d for d in pack.motive_defs if d.key == motives[effect(Axis.WHY)[0]])
        return all_of(list(motive.secrets), who(fact.source.subject))
    if kind in (FactKind.PRESENCE, FactKind.ALIBI):
        assert fact.claim is not None
        values = {
            **who(fact.claim.actor),
            **where(fact.claim.place),
            **slots.slot_time(pack, fact.claim.slot),
            **record,
        }
        return all_of(_family(pack, "record"), values)
    if kind is FactKind.PHYSICAL:
        family = "physical_proof" if effect(Axis.WHO)[1] is EffectKind.PROVES else "physical_clear"
        return all_of(_family(pack, family), {**who(fact.source.subject), **record})
    if kind is FactKind.MOTIVE_CLUE:
        motive = next(d for d in pack.motive_defs if d.key == motives[effect(Axis.WHY)[0]])
        return all_of(list(motive.hints), who(fact.speaker))
    if kind is FactKind.LIE:
        assert fact.claim is not None and fact.exposure_hook is not None
        values = {
            **who(fact.claim.actor),
            **where(fact.claim.place),
            **slots.slot_time(pack, fact.claim.slot),
            **slots.record_name(pack, fact.exposure_hook.target),
        }
        return all_of(_family(pack, "lie"), values)
    if kind in (FactKind.TRACE, FactKind.ABSENT_TRACE):
        method = next(d for d in pack.method_defs if d.key == methods[effect(Axis.HOW)[0]])
        trace = next(t for t in method.traces if t.kind == fact.trace_kind)
        texts = trace.templates if kind is FactKind.TRACE else trace.absent
        return all_of(list(texts), where(fact.source.target))
    if fact.source.kind is SourceKind.RECORD:
        definition = next(d for d in pack.record_defs if d.key == fact.source.target)
        return all_of(list(definition.entries), record)
    if fact.effects:
        method = next(d for d in pack.method_defs if d.key == methods[effect(Axis.HOW)[0]])
        return all_of(list(method.clues), where(fact.source.target))
    holder = next(s for s in case.suspects if fact.id in s.requires)
    return all_of(_family(pack, "key"), who(holder.id))


def welch_z(a: list[float], b: list[float]) -> float:
    """How many standard errors apart the means of two samples are."""
    from math import sqrt
    from statistics import fmean, variance

    spread = variance(a) / len(a) + variance(b) / len(b)
    return (fmean(a) - fmean(b)) / sqrt(spread) if spread else 0.0


def renderings(case: Case, pack: Pack, fact: Fact) -> set[str]:
    return set(rendered(case, pack, fact))
