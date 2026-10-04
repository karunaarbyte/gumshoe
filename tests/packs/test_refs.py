from gumshoe.cases.model.pack import MethodDef, Pack, SlotDef, TraceDef
from gumshoe.cases.packs.check import refs
from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS, rich_pack
from tests.packs.mutations import replace


def paths(text: str) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in load_pack(text.encode(), TEST_PRESETS).issues]


def test_an_unknown_scene_location_kind_names_the_value_and_suggests_known_ones():
    text = replace('location_kinds = ["study"]', 'location_kinds = ["crypt"]')(BASE_TOML)
    result = load_pack(text.encode(), TEST_PRESETS)
    (issue,) = result.issues
    assert issue.path == "scene_types.study_murder.location_kinds[crypt]"
    assert issue.suggestion == "known: cellar, garden, study"


def test_a_trace_naming_an_unknown_location_kind_gets_a_did_you_mean():
    text = replace(
        'kind = "wound"\nlocation_kinds = ["cellar", "garden", "study"]',
        'kind = "wound"\nlocation_kinds = ["celar"]',
    )(BASE_TOML)
    (issue,) = load_pack(text.encode(), TEST_PRESETS).issues
    assert issue.code == "UNKNOWN_LOCATION_KIND"
    assert issue.path == "method_defs.dagger.traces[wound].location_kinds[celar]"
    assert issue.suggestion.startswith("did you mean 'cellar'?")


def test_a_reference_error_stops_the_later_stages():
    text = replace('location_kinds = ["study"]', 'location_kinds = ["crypt"]')(BASE_TOML)
    text = text.replace("{^place} smells of ink and cold ash.", "{^place} smells of {oops")
    assert {c for c, _ in paths(text)} == {"UNKNOWN_LOCATION_KIND"}  # no template issue yet


def test_duplicate_keys_in_model_built_packs_are_reported_with_the_key():
    pack = rich_pack(
        slot_defs=(SlotDef(key="a", at="at a", during="during a"),) * 2,
        method_defs=(
            MethodDef(key="m", label="l", traces=(TraceDef(kind="k"), TraceDef(kind="k"))),
            MethodDef(key="m", label="l"),
        ),
    )
    found = {(i.code, i.path) for i in refs.check(pack)}
    assert ("DUPLICATE_KEY", "slot_defs[a]") in found
    assert ("DUPLICATE_KEY", "method_defs[m]") in found
    assert ("DUPLICATE_KEY", "method_defs.m.traces[k]") in found


def test_a_valid_rich_pack_has_no_reference_issues():
    assert refs.check(rich_pack()) == []


def test_a_pack_with_nothing_declared_has_no_reference_issues():
    assert refs.check(Pack(id="e", capacity=rich_pack().capacity)) == []


def test_a_record_kind_declared_without_a_record_def_is_still_known():
    pack = rich_pack(record_kinds=("ledger",), record_defs=())
    assert pack.roles[0].record_kinds == ("ledger",)
    assert refs.check(pack) == []


def test_a_preset_claimed_twice_is_a_duplicate_key():
    text = replace('presets = ["tiny"]', 'presets = ["short", "short"]')(BASE_TOML)
    assert paths(text) == [("DUPLICATE_KEY", "meta.presets[short]")]
    assert ("DUPLICATE_KEY", "meta.presets[tiny]") in {
        (i.code, i.path) for i in refs.check(rich_pack(presets=("tiny", "tiny")))
    }


def test_a_record_location_kind_that_is_not_defined_is_reported_with_its_path():
    record = rich_pack().record_defs[0].model_copy(update={"location_kinds": ("crypt", "study")})
    (issue,) = refs.check(rich_pack(record_defs=(record,)))
    assert (issue.code, issue.path) == (
        "UNKNOWN_LOCATION_KIND",
        "record_defs.ledger.location_kinds[crypt]",
    )
    assert issue.suggestion.startswith("known:") or "did you mean" in issue.suggestion
