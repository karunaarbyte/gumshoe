"""The castle's wording for the evidence (2c.1b): the house rules for every new text."""

import re
from collections.abc import Iterator

import pytest

from gumshoe.cases.core.labels import token_set
from gumshoe.cases.model.pack import FamilyDef, Pack
from gumshoe.cases.packs.check.lint import (
    KNOWN_PLACEHOLDERS,
    SAMPLES,
    blank_placeholders,
    placeholders,
    render,
)
from gumshoe.cases.tools.builtin import load_builtin_pack
from tests.packs.test_castle import (
    AUDIENCES,
    BODY_WORDS,
    CERTAINTY_WORDS,
    HARD_CODED_RECORD_NAMES,
    NEGATIONS,
    SAMPLE,
    WITNESS_NOUNS,
    _found,
    _slots,
    _union,
)

NEW_FAMILIES = {
    "physical_proof": {"who", "record"},
    "physical_clear": {"who", "record"},
    "key": {"who"},
    "contradiction": {"who", "place.in", "time.at", "record"},
    "intro": {"victim", "place.in", "time.during"},
}
PHYSICAL_NOUNS = ("cloak", "boots", "gloves", "sleeve", "belt", "apron", "cap", "hat")


@pytest.fixture
def pack() -> Pack:
    return load_builtin_pack("castle")


def _family(pack: Pack, kind: str) -> FamilyDef:
    (found,) = [f for f in pack.families if f.kind == kind]
    return found


def _owned(pack: Pack) -> Iterator[tuple[str, str]]:
    """Every owned text with its key path: absent, clues, hints and the location-record entries."""
    for method in pack.method_defs:
        for trace in method.traces:
            for i, text in enumerate(trace.absent):
                yield f"method_defs.{method.key}.traces[{trace.kind}].absent[{i}]", text
        for i, text in enumerate(method.clues):
            yield f"method_defs.{method.key}.clues[{i}]", text
    for motive in pack.motive_defs:
        for i, text in enumerate(motive.hints):
            yield f"motive_defs.{motive.key}.hints[{i}]", text
    for record in pack.record_defs:
        for i, text in enumerate(record.entries):
            yield f"record_defs.{record.key}.entries[{i}]", text


def _new_texts(pack: Pack) -> list[str]:
    families = [t for kind in NEW_FAMILIES for t in _family(pack, kind).variants]
    return [*families, *(text for _, text in _owned(pack))]


def test_the_five_new_families_exist_once_with_their_ids_kinds_and_slots(pack):
    for kind, slots in NEW_FAMILIES.items():
        family = _family(pack, kind)
        assert family.id == kind
        assert set(family.claim_slots) == slots, kind
        assert len(family.variants) >= 7, kind
        for variant in family.variants:
            assert slots <= _slots(variant), variant


def test_the_skin_revision_moved_with_the_new_wording(pack):
    assert pack.skin_rev >= 2


def test_the_two_physical_families_pair_up_variant_by_variant(pack):
    proof, clear = _family(pack, "physical_proof"), _family(pack, "physical_clear")
    assert len(proof.variants) == len(clear.variants)
    assert _union(proof.variants, PHYSICAL_NOUNS) == _union(clear.variants, PHYSICAL_NOUNS)
    assert _union(proof.variants, WITNESS_NOUNS) == _union(clear.variants, WITNESS_NOUNS)
    assert _union(proof.variants, AUDIENCES) == _union(clear.variants, AUDIENCES)
    for a, b in zip(proof.variants, clear.variants, strict=True):
        assert _slots(a) == _slots(b) == {"who", "record"}, (a, b)
        assert _union([a], PHYSICAL_NOUNS) == _union([b], PHYSICAL_NOUNS), (a, b)
    mean_proof = sum(len(render(t, SAMPLES[0])) for t in proof.variants) / len(proof.variants)
    mean_clear = sum(len(render(t, SAMPLES[0])) for t in clear.variants) / len(clear.variants)
    assert abs(mean_proof - mean_clear) <= 0.1 * max(mean_proof, mean_clear)


def test_the_physical_and_contradiction_texts_name_their_record_by_placeholder(pack):
    texts = [
        t
        for k in ("physical_proof", "physical_clear", "contradiction")
        for t in _family(pack, k).variants
    ]
    assert _found(texts, HARD_CODED_RECORD_NAMES) == []
    assert all("record" in _slots(t) for t in texts)


def test_the_physical_texts_state_no_place_and_no_time(pack):
    for kind in ("physical_proof", "physical_clear"):
        for variant in _family(pack, kind).variants:
            assert not {"place", "place.in", "time.at", "time.phrase", "time.during"} & _slots(
                variant
            )


def test_the_intro_names_no_suspect_role_and_says_who_died_where_and_when(pack):
    roles = [r.key for r in pack.roles] + [r.noun for r in pack.roles]
    variants = _family(pack, "intro").variants
    assert _found(variants, roles) == []
    for variant in variants:
        assert {"victim", "place.in", "time.during"} <= _slots(variant)
    named = token_set(
        *(x for d in (*pack.method_defs, *pack.motive_defs) for x in (d.label, *d.aliases))
    )
    for variant in variants:
        assert not token_set(blank_placeholders(variant)) & named, variant


def test_no_new_text_states_a_certainty_or_a_negation(pack):
    texts = _new_texts(pack)
    assert _found(texts, CERTAINTY_WORDS) == []
    assert _found(texts, NEGATIONS) == []


def test_every_new_text_is_one_sentence_ending_in_a_full_stop(pack):
    for text in _new_texts(pack):
        assert text.endswith(".") and text.count(". ") == 0, text


def test_no_two_new_texts_render_to_the_same_sentence(pack):
    rendered = [render(t, SAMPLE) for t in _new_texts(pack)]
    assert sorted({s for s in rendered if rendered.count(s) > 1}) == []


def test_every_new_text_renders_with_every_sample_to_a_clean_sentence(pack):
    for text in _new_texts(pack):
        assert set(placeholders(text)) <= KNOWN_PLACEHOLDERS, text
        for sample in (*SAMPLES, SAMPLE):
            out = render(text, sample)
            assert "{" not in out and "}" not in out and "  " not in out, (text, out)
            assert out[0].isupper(), (text, out)
            assert not re.search(r"\s[.,]", out), (text, out)


def test_a_wording_edit_keeps_the_skeleton_hash_and_dropping_a_family_changes_it(pack):
    hints = ("An edited hint.", *pack.motive_defs[0].hints[1:])
    motives = (pack.motive_defs[0].model_copy(update={"hints": hints}), *pack.motive_defs[1:])
    assert pack.model_copy(update={"motive_defs": motives}).skeleton_hash() == pack.skeleton_hash()
    kept = tuple(f for f in pack.families if f.kind != "intro")
    assert pack.model_copy(update={"families": kept}).skeleton_hash() != pack.skeleton_hash()


def test_absent_texts_and_clues_describe_objects_not_bodies(pack):
    owned = [t for p, t in _owned(pack) if ".absent[" in p or ".clues[" in p]
    assert owned and _found(owned, BODY_WORDS) == []


def test_every_method_has_as_many_absent_texts_as_templates_and_three_clues(pack):
    for method in pack.method_defs:
        for trace in method.traces:
            assert len(trace.absent) == len(trace.templates) == 2, method.key
        assert len(method.clues) == 3, method.key
        for text in (t for tr in method.traces for t in tr.absent):
            assert "place.in" in _slots(text), text
        for text in method.clues:
            assert "place.in" in _slots(text), text
