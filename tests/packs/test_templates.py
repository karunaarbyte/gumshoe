import pytest

from gumshoe.cases.model.pack import FamilyDef
from gumshoe.cases.packs.check import templates
from gumshoe.cases.packs.check.lint import template_items
from tests.packs.fixtures import rich_pack


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
