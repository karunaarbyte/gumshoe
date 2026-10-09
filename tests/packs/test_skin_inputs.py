import pytest

from gumshoe.cases.model.pack import Entry, FamilyDef, Pack
from gumshoe.cases.packs.check import skin_inputs
from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import SKIN_BASE_TOML, TEST_PRESETS
from tests.packs.mutations import MUTATIONS, STAGE_8_CODES
from tests.packs.test_skin_texts import with_method, with_motive, with_trace


def base() -> Pack:
    pack = load_pack(SKIN_BASE_TOML.encode(), TEST_PRESETS).pack
    assert pack is not None
    return pack


def found(pack: Pack) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in skin_inputs.check(pack)]


def with_family(pack: Pack, family_id: str, **changes: object) -> Pack:
    families = tuple(
        f.model_copy(update=changes) if f.id == family_id else f for f in pack.families
    )
    return pack.model_copy(update={"families": families})


def test_the_clean_skin_base_has_no_stage_8_issue():
    assert found(base()) == []


def test_an_empty_pack_reports_every_gap_and_never_crashes():
    codes = {c for c, _ in found(Pack(id="e", capacity=base().capacity))}
    assert codes == {"MISSING_FAMILY", "TOO_FEW_TEXTS"}


def test_a_missing_required_family_is_named_by_its_kind():
    pack = base().model_copy(
        update={"families": tuple(f for f in base().families if f.id != "key")}
    )
    assert found(pack) == [("MISSING_FAMILY", "families.key")]
    (issue,) = skin_inputs.check(pack)
    assert "'key'" in issue.message


def test_a_second_family_of_a_required_kind_is_reported_at_the_extra_family():
    extra = FamilyDef(id="intro_two", kind="intro", claim_slots=("victim",), variants=("x",))
    pack = base().model_copy(update={"families": (*base().families, extra)})
    assert found(pack) == [("DUPLICATE_FAMILY_KIND", "families.intro_two")]


def test_each_list_has_its_own_minimum():
    pack = with_trace(base(), "dagger", absent=("Only one.",))
    assert ("TOO_FEW_TEXTS", "method_defs.dagger.traces[wound].absent") in found(pack)
    assert ("TOO_FEW_TEXTS", "method_defs.rope.clues") in found(
        with_method(base(), "rope", clues=("a", "b"))
    )
    assert ("TOO_FEW_TEXTS", "motive_defs.debt.hints") in found(
        with_motive(base(), "debt", hints=("a", "b"))
    )
    records = tuple(
        r.model_copy(update={"entries": ("a", "b")}) if r.key == "gate_log" else r
        for r in base().record_defs
    )
    assert ("TOO_FEW_TEXTS", "record_defs.gate_log.entries") in found(
        base().model_copy(update={"record_defs": records})
    )
    assert ("TOO_FEW_TEXTS", "victims") in found(
        base().model_copy(update={"victims": base().victims[:5]})
    )
    assert ("TOO_FEW_TEXTS", "meta.smalltalk_allow") in found(
        base().model_copy(update={"smalltalk_allow": base().smalltalk_allow[:19]})
    )


def test_only_a_record_kind_about_a_place_needs_entries():
    # the ledger is about a suspect: no entries, and no issue
    assert all(p != "record_defs.ledger.entries" for _, p in found(base()))


def test_a_victim_without_a_pronoun_or_proper_and_a_role_without_a_style_are_incomplete():
    victims = (
        Entry(text="Lord Aldric", proper=True),
        Entry(text="Lord Godwin", pronoun="he"),
        *base().victims[2:],
    )
    pack = base().model_copy(update={"victims": victims})
    assert found(pack) == [("ENTRY_INCOMPLETE", "victims[0]"), ("ENTRY_INCOMPLETE", "victims[1]")]
    roles = tuple(
        r.model_copy(update={"style": "  "}) if r.key == "cook" else r for r in base().roles
    )
    pack = base().model_copy(update={"roles": roles})
    assert found(pack) == [("ENTRY_INCOMPLETE", "roles.cook.style")]


def test_a_candidate_with_fewer_texts_than_the_largest_is_a_count_skew():
    clue = "A whetstone {place.in} was still wet, with fresh grey streaks."
    pack = with_method(base(), "dagger", clues=(clue,) * 4)
    assert found(pack) == [
        ("TEXT_COUNT_SKEW", "method_defs.poison.clues"),
        ("TEXT_COUNT_SKEW", "method_defs.rope.clues"),
    ]
    hint = "{^who} fell silent whenever the favourite was praised."
    pack = with_motive(base(), "jealousy", hints=(hint,) * 4)
    assert ("TEXT_COUNT_SKEW", "motive_defs.debt.hints") in found(pack)


def test_a_candidates_texts_much_longer_than_the_rest_are_a_length_skew():
    pack = with_method(base(), "rope", clues=("x" * 90,) * 3)
    assert found(pack) == [("TEXT_LENGTH_SKEW", "method_defs.rope.clues")]


def test_absent_texts_far_from_the_trace_templates_in_length_are_a_pack_wide_skew():
    pack = base()
    for key in ("dagger", "poison", "rope"):
        pack = with_trace(pack, key, absent=("Short one.", "Short two."))
    assert found(pack) == [("TEXT_LENGTH_SKEW", "method_defs")]


def test_the_physical_pair_must_match_in_count_mean_and_range():
    proof = [f for f in base().families if f.id == "physical_proof"][0]
    longer = with_family(base(), "physical_proof", variants=(*proof.variants, "One more."))
    assert found(longer) == [("PAIR_COUNT_SKEW", "families.physical_clear")]
    narrow_a = with_family(base(), "physical_proof", variants=("x" * 70,) * 5)
    narrow_b = with_family(narrow_a, "physical_clear", variants=("x" * 72,) * 5)
    (issue,) = skin_inputs.check(narrow_b)  # close means, but the ranges do not overlap
    assert issue.code == "PAIR_LENGTH_SKEW" and "do not overlap" in issue.message
    skewed = with_family(base(), "physical_proof", variants=("x" * 140,) * 5)
    assert ("PAIR_LENGTH_SKEW", "families.physical_clear") in found(skewed)


def test_the_small_talk_list_may_hold_only_one_plain_word_that_is_no_candidates_token():
    cases = {
        "two words": "good day",
        "Capital": "Hello",
        "don't": "don't",
        "the": "the",  # a stopword is no token
        "wine": "wine",  # a token of the poison method's alias
        "stabbing": "stabbing",  # stems to the dagger's token
        "maid": "maid",  # a role noun
        "edmund": "edmund",  # a role name
        "debt": "debt",  # a motive token
    }
    for label, word in cases.items():
        words = ("ale", "bread", "breakfast", *base().smalltalk_allow[3:], word)
        pack = base().model_copy(update={"smalltalk_allow": tuple(sorted(set(words)))})
        codes = [c for c, _ in found(pack)]
        assert codes == ["BAD_SMALLTALK_WORD"], label


def test_a_repeated_small_talk_word_is_reported():
    pack = base().model_copy(update={"smalltalk_allow": (*base().smalltalk_allow, "ale")})
    assert found(pack) == [("BAD_SMALLTALK_WORD", "meta.smalltalk_allow[20]")]


@pytest.mark.parametrize("code", sorted(STAGE_8_CODES))
def test_stage_8_mutation_reports_exactly_its_declared_cascade(code):
    mutation = MUTATIONS[code]
    result = load_pack(mutation.apply(SKIN_BASE_TOML).encode(), TEST_PRESETS)
    assert result.pack is not None
    codes = {i.code for i in result.issues} | {i.code for i in skin_inputs.check(result.pack)}
    assert codes == mutation.expected, found(result.pack)
