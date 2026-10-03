import pytest

from gumshoe.cases.model.pack import FamilyDef
from gumshoe.cases.packs.check import templates
from gumshoe.cases.packs.check.lint import pack_sample, template_items
from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS, rich_pack
from tests.packs.mutations import replace


def codes(pack):
    return [(i.code, i.path) for i in templates.check(pack)]


def test_the_rich_pack_has_no_template_issues():
    assert codes(rich_pack(families=(_family(5),))) == []


def _family(n: int, claim_slots=("who",)) -> FamilyDef:
    return FamilyDef(
        id="alibi",
        kind="alibi",
        claim_slots=claim_slots,
        variants=tuple(f"{{^who}} was seen on day{i}." for i in range(n)),
    )


def test_a_family_needs_five_variants_or_seven_when_the_pack_claims_long():
    assert ("TOO_FEW_VARIANTS", "families.alibi") in codes(rich_pack(families=(_family(4),)))
    assert codes(rich_pack(families=(_family(5),), presets=("tiny",))) == []
    assert ("TOO_FEW_VARIANTS", "families.alibi") in codes(
        rich_pack(families=(_family(6),), presets=("long",))
    )
    assert codes(rich_pack(families=(_family(7),), presets=("long",))) == []


@pytest.mark.parametrize("bad", ["{who", "{{who}}", "who} left", "{}"])
def test_stray_brace_text_gives_one_brace_issue_and_no_cascade(bad):
    pack = rich_pack(families=(FamilyDef(id="a", kind="a", variants=(bad,) * 5),))
    found = {c for c, _ in codes(pack)}
    assert found <= {"UNRESOLVED_BRACE", "UNKNOWN_PLACEHOLDER"} and found


def test_an_unknown_claim_slot_is_an_unknown_placeholder_on_the_claim_slot_path():
    pack = rich_pack(families=(_family(5, claim_slots=("whom",)),))
    assert ("UNKNOWN_PLACEHOLDER", "families.alibi.claim_slots[whom]") in codes(pack)


def test_template_items_cover_every_templated_table():
    paths = [p for p, _ in template_items(rich_pack())]
    assert "location_defs.study.descriptions[0]" in paths
    assert "record_defs.ledger.presence[0]" in paths
    assert "method_defs.poison.traces[residue].templates[0]" in paths
    assert "motive_defs.debt.secrets[0]" in paths
    assert "families.alibi.variants[0]" in paths


def loaded(old: str, new: str) -> set[tuple[str, str]]:
    result = load_pack(replace(old, new)(BASE_TOML).encode(), TEST_PRESETS)
    assert result.pack is not None
    return {(i.code, i.path) for i in result.issues}


def test_a_broken_slot_phrase_is_linted_at_its_own_path():
    found = loaded('during = "during the midday meal"', 'during = "during the the {noon  meal"')
    path = "slot_defs[noon].during"
    assert found == {("UNRESOLVED_BRACE", path), ("DOUBLE_SPACE", path), ("DOUBLED_WORD", path)}
    assert loaded('at = "at noon"', 'at = "at an noon"') == {
        ("ARTICLE_MISMATCH", "slot_defs[noon].at")
    }


def test_a_pool_entry_is_linted_with_its_article():
    found = loaded('{ text = "Study", article = "the" }', '{ text = "Study", article = "an" }')
    assert found == {("ARTICLE_MISMATCH", "location_defs.study.names[0]")}
    # the maid is not the first role, so the pack sample (and every template) is unaffected
    found = loaded('{ text = "Maud", pronoun', '{ text = "Maud  Maud", pronoun')
    assert found == {
        ("DOUBLE_SPACE", "roles.maid.names[0]"),
        ("DOUBLED_WORD", "roles.maid.names[0]"),
    }


def test_a_trait_with_braces_is_an_unresolved_brace_and_still_leaks_its_token():
    found = loaded('"quiet and watchful"', '"{oops handy with a {dagger}"')
    assert found == {
        ("UNRESOLVED_BRACE", "roles.maid.traits[0]"),
        ("LABEL_TOKEN_LEAK", "roles.maid.traits[0]"),
    }


def test_method_and_motive_labels_and_aliases_are_linted():
    assert loaded('"poison", "laced wine"', '"poison", "laced  wine"') == {
        ("DOUBLE_SPACE", "method_defs.poison.aliases[0]")  # aliases are sorted
    }
    assert loaded('"to claim an inheritance"', '"to claim a inheritance"') == {
        ("ARTICLE_MISMATCH", "motive_defs.inheritance.label")
    }


def test_templates_are_also_rendered_with_the_packs_own_first_values():
    # "The Cellar cellar" only with the pack's own first location; the fixed samples miss it
    found = loaded("{^place} is damp, low", "{^place} cellar is damp, low")
    assert found == {("DOUBLED_WORD", "location_defs.cellar.descriptions[0]")}


def test_the_pack_sample_takes_the_first_pool_values_and_falls_back_to_the_fixed_one():
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    assert pack is not None
    sample = pack_sample(pack)
    assert sample["place"] == "the Cellar" and sample["place.in"] == "in the Cellar"
    assert sample["time.at"] == "at dawn" and sample["time.during"] == "during the dawn watch"
    assert (sample["who"], sample["who.subj"], sample["who.poss"]) == ("Hob", "he", "his")
    assert sample["item.a"] == "a lantern"
    empty = pack_sample(rich_pack(roles=(), slot_defs=(), location_defs=()))
    assert empty["who"] == "Edmund" and empty["place"] == "the Chapel"
