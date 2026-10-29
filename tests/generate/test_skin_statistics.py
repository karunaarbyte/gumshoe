"""Does the wording tell truth from lie? A player compares the texts of one case, so every test
here is the attack a player could make inside a case ("the true one is the shortest, has the
fewest commas, names its method least") compared with chance over many seeds, plus a few pooled
checks. Each is one z test at the Bonferroni level of the other generator statistics
(`Z_BONFERRONI`); a failure means the pack's wording needs a rewrite, never that the bound
should be loosened."""

import re
from collections import Counter
from collections.abc import Callable
from functools import cache
from math import sqrt

import pytest

from gumshoe.cases.core.text import tokens
from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind, SourceKind
from gumshoe.cases.packs.check.hygiene import candidate_tokens
from gumshoe.cases.packs.check.lint import phrase
from tests.generate.helpers import PACKS, Z_BONFERRONI, chi2_critical, chi2_statistic
from tests.generate.skin_helpers import made, pack_for, rendered, welch_z

SEEDS = range(150)
PRESETS = ("short", "standard", "long")


@pytest.fixture(params=PACKS)
def pack_id(request) -> str:
    return request.param


@cache
def owned(pack_id: str) -> dict[str, frozenset[str]]:
    return candidate_tokens(pack_for(pack_id))


@cache
def corpus(pack_id: str) -> list[Case]:
    return [made(seed, preset, pack_id) for preset in PRESETS for seed in SEEDS]


def who_proves(f: Fact) -> bool:
    return any(e.axis is Axis.WHO and e.kind is EffectKind.PROVES for e in f.effects)


def decisive(case: Case) -> tuple[Fact, list[Fact]]:
    """The facts that decide the method: one true trace among the absent ones."""
    group = [f for f in case.facts if f.kind in (FactKind.TRACE, FactKind.ABSENT_TRACE)]
    return next(f for f in group if f.kind is FactKind.TRACE), group


def physical(case: Case) -> tuple[Fact, list[Fact]]:
    group = [f for f in case.facts if f.kind is FactKind.PHYSICAL]
    return next(f for f in group if who_proves(f)), group


def hints(case: Case) -> tuple[Fact, list[Fact]]:
    group = [f for f in case.facts if f.kind is FactKind.MOTIVE_CLUE]
    return next(f for f in group if f.effects[0].candidate == case.truth.why), group


def secrets(case: Case) -> tuple[Fact, list[Fact]]:
    group = [f for f in case.facts if f.kind is FactKind.SECRET]
    return next(f for f in group if any(e.kind is EffectKind.PROVES for e in f.effects)), group


GROUPS = {"trace": decisive, "physical": physical, "hint": hints, "secret": secrets}


def bare(pack_id: str, case: Case, fact: Fact) -> str:
    """The text without the place phrase (its words belong to the location, not to the truth)."""
    if fact.source.kind is not SourceKind.SEARCH:
        return fact.text
    location = next(x for x in case.locations if x.id == fact.source.target)
    where = phrase(slots.place_entry(pack_for(pack_id), location))
    return fact.text.replace(f"in {where}", "").replace(where, "")


def method_names(pack_id: str, case: Case, fact: Fact) -> int:
    method = next(m for m in case.methods if m.id == fact.effects[0].candidate)
    return len(set(tokens(fact.text)) & owned(pack_id)[f"method:{method.type}"])


def place_position(pack_id: str, case: Case, fact: Fact) -> float:
    location = next(x for x in case.locations if x.id == fact.source.target)
    return fact.text.find(phrase(slots.place_entry(pack_for(pack_id), location))) / len(fact.text)


FEATURES: dict[str, Callable[[str, Case, Fact], float]] = {
    "words": lambda p, c, f: len(re.findall(r"[A-Za-z']+", bare(p, c, f))),
    "characters": lambda p, c, f: len(bare(p, c, f)),
    "commas": lambda p, c, f: f.text.count(","),
    "names its method": method_names,
    "place position": place_position,
}


def attack_z(pack_id: str, group: str, feature: str, pick: Callable[..., float]) -> float:
    """z of "the true text is the one with the lowest (or highest) value", against chance. Ties
    share the credit; a case whose group has fewer than two texts is left out."""
    hits = chance = variance = 0.0
    for case in corpus(pack_id):
        true, texts = GROUPS[group](case)
        if len(texts) < 2:
            continue
        values = [FEATURES[feature](pack_id, case, f) for f in texts]
        best = pick(values)
        tops = [f for f, v in zip(texts, values, strict=True) if v == best]
        hits += 1 / len(tops) if true in tops else 0
        p = 1 / len(texts)
        chance += p
        variance += p * (1 - p)
    return (hits - chance) / sqrt(variance)


ATTACKS = [
    (group, feature)
    for group in GROUPS
    for feature in FEATURES
    if feature not in ("names its method", "place position") or group == "trace"
]


@pytest.mark.parametrize("pick", [min, max], ids=["lowest", "highest"])
@pytest.mark.parametrize(("group", "feature"), ATTACKS)
def test_the_true_text_of_a_case_is_not_the_lowest_or_highest_in_any_feature(
    pack_id, group, feature, pick
):
    z = attack_z(pack_id, group, feature, pick)
    assert abs(z) < Z_BONFERRONI, (group, feature, pick.__name__, z)


@pytest.mark.parametrize("axis", ["how", "why"])
@pytest.mark.parametrize("pick", [min, max], ids=["fewest", "most"])
def test_the_true_method_or_motive_is_not_the_one_named_in_fewest_or_most_texts(
    pack_id, axis, pick
):
    hits = chance = variance = 0.0
    for case in corpus(pack_id):
        items = case.methods if axis == "how" else case.motives
        prefix = "method" if axis == "how" else "motive"
        true = case.truth.how if axis == "how" else case.truth.why
        words = [set(tokens(f.text)) for f in case.facts]
        counts = {
            c.id: sum(1 for have in words if have & owned(pack_id)[f"{prefix}:{c.type}"])
            for c in items
        }
        best = pick(counts.values())
        tops = [i for i, n in counts.items() if n == best]
        hits += 1 / len(tops) if true in tops else 0
        chance += 1 / len(items)
        variance += (1 / len(items)) * (1 - 1 / len(items))
    assert abs((hits - chance) / sqrt(variance)) < Z_BONFERRONI


def lengths(pack_id: str, kind: FactKind, keep: Callable[[Fact], bool]) -> list[float]:
    return [len(f.text) for c in corpus(pack_id) for f in c.facts if f.kind is kind and keep(f)]


def test_pooled_the_culprits_physical_text_is_no_longer_than_a_cleared_suspects(pack_id):
    z = welch_z(
        lengths(pack_id, FactKind.PHYSICAL, who_proves),
        lengths(pack_id, FactKind.PHYSICAL, lambda f: not who_proves(f)),
    )
    assert abs(z) < Z_BONFERRONI, z


def test_pooled_the_true_motive_hint_is_no_longer_than_the_others(pack_id):
    true: list[float] = []
    false: list[float] = []
    for c in corpus(pack_id):
        for f in c.facts:
            if f.kind is FactKind.MOTIVE_CLUE:
                (true if f.effects[0].candidate == c.truth.why else false).append(len(f.text))
    assert abs(welch_z(true, false)) < Z_BONFERRONI


def test_pooled_the_true_method_is_named_in_as_many_texts_as_a_false_one(pack_id):
    true: list[float] = []
    false: list[float] = []
    for c in corpus(pack_id):
        words = [set(tokens(f.text)) for f in c.facts]
        for m in c.methods:
            named = sum(1 for have in words if have & owned(pack_id)[f"method:{m.type}"])
            (true if m.id == c.truth.how else false).append(named)
    assert abs(welch_z(true, false)) < Z_BONFERRONI


@pytest.mark.parametrize("which", ["physical proof", "true trace"])
def test_the_variant_a_fact_gets_does_not_depend_on_whether_it_is_the_true_one(pack_id, which):
    counts: Counter[int] = Counter()
    cells = 0
    for case in corpus(pack_id):
        fact = (physical if which == "physical proof" else decisive)(case)[0]
        texts = rendered(case, pack_for(pack_id), fact)
        cells = len(texts)
        counts[texts.index(fact.text)] += 1
    total = sum(counts.values())
    expected = {i: total / cells for i in range(cells)}
    assert chi2_statistic(counts, expected) < chi2_critical(cells - 1), counts
