from importlib.resources import files

import pytest

from gumshoe.cases.packs.loader import load_pack, reshape
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS
from tests.packs.mutations import replace


def load(text: str):
    return load_pack(text.encode(), TEST_PRESETS)


def codes_and_paths(text: str) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in load(text).issues]


def test_the_loaded_pack_has_every_table_and_the_derived_record_kinds():
    pack = load(BASE_TOML).pack
    assert pack is not None
    assert pack.id == "tiny" and pack.presets == ("tiny",)
    assert [d.key for d in pack.method_defs] == ["dagger", "poison", "rope"]
    assert pack.record_kinds == ("gate_log", "ledger")
    assert [s.key for s in pack.slot_defs] == ["dawn", "noon", "dusk", "night"]
    assert pack.method_defs[0].traces[0].kind == "wound"


def test_a_wrong_type_reports_the_key_path_and_the_pack_is_none():
    result = load(replace("slots = 4", 'slots = "four"')(BASE_TOML))
    assert result.pack is None
    assert codes_and_paths(replace("slots = 4", 'slots = "four"')(BASE_TOML)) == [
        ("WRONG_TYPE", "meta.slots")
    ]


@pytest.mark.parametrize("prep", ["", "In", "on2"])
def test_a_bad_preposition_is_refused(prep):
    text = replace(
        'names = [{ text = "Study", article = "the" }]',
        f'names = [{{ text = "Study", article = "the", prep = "{prep}" }}]',
    )(BASE_TOML)
    assert load(text).pack is None
    assert any("prep" in path for _, path in codes_and_paths(text))


def test_keyed_tables_report_the_key_not_an_index():
    text = replace('label = "stabbed with a dagger"\n', "")(BASE_TOML)
    assert codes_and_paths(text) == [("MISSING_FIELD", "method_defs.dagger.label")]


def test_list_items_are_named_by_key_or_id_and_fall_back_to_an_index():
    text = replace('kind = "wound"\n', 'kind = "wound"\ncolour = "red"\n')(BASE_TOML)
    assert codes_and_paths(text) == [("UNKNOWN_KEY", "method_defs.dagger.traces[0].colour")]
    text = replace('claim_slots = ["who", "time.at"]', 'claim_slots = "who"')(BASE_TOML)
    assert codes_and_paths(text) == [("WRONG_TYPE", "families.presence_record.claim_slots")]
    text = replace('id = "presence_record"', "id = 7")(BASE_TOML)
    assert codes_and_paths(text) == [("WRONG_TYPE", "families[1].id")]  # no usable name


def test_a_misspelled_section_suggests_the_right_one():
    result = load(BASE_TOML.replace("[capacity]", "[capacitty]"))
    unknown = [i for i in result.issues if i.code == "UNKNOWN_KEY"]
    assert [i.path for i in unknown] == ["capacitty"]
    assert unknown[0].suggestion.startswith("did you mean 'capacity'?")
    assert "MISSING_FIELD" in {i.code for i in result.issues}  # capacity itself is gone


def test_an_invalid_enum_value_is_a_wrong_type_with_the_allowed_values():
    text = replace('subject = "suspect"', 'subject = "room"')(BASE_TOML)
    (issue,) = load(text).issues
    assert issue.code == "WRONG_TYPE" and issue.path == "record_defs.ledger.subject"
    assert "'suspect', 'location' or 'event'" in issue.message


def test_an_empty_file_gives_issues_not_an_exception():
    result = load("")
    assert result.pack is None
    assert {i.code for i in result.issues} == {"MISSING_FIELD"}
    assert {i.path for i in result.issues} == {"meta.id", "capacity"}


def test_bytes_that_are_not_utf8_are_a_toml_syntax_issue():
    result = load_pack(b"\xff\xfe\x00bad", TEST_PRESETS)
    assert result.pack is None and [i.code for i in result.issues] == ["TOML_SYNTAX"]


def test_reshape_turns_keyed_tables_into_keyed_lists_and_ignores_unknown_sections():
    out = reshape({"meta": {"id": "x"}, "roles": {"cook": {"traits": []}}, "bogus": {}})
    assert out["id"] == "x" and out["roles"] == [{"key": "cook", "traits": []}]
    assert "bogus" not in out


def test_a_section_of_the_wrong_shape_is_a_wrong_type_not_a_crash():
    block = (
        "[capacity]\nmax_suspects = 3\nmax_locations = 3\nmax_methods = 3\nmax_record_kinds = 2\n"
    )
    text = "capacity = 5\n" + replace(block, "")(BASE_TOML)
    assert codes_and_paths(text) == [("WRONG_TYPE", "capacity")]


def test_a_key_field_inside_a_keyed_table_never_crashes_and_the_table_key_wins():
    text = replace("[record_defs.gate_log]\n", "[record_defs.gate_log]\nkey = 5\n")(BASE_TOML)
    result = load(text)
    assert result.pack is not None
    assert result.pack.record_kinds == ("gate_log", "ledger")


def test_deeply_nested_input_is_a_toml_syntax_issue_not_a_recursion_error():
    result = load_pack(b"x = " + b"[" * 5000, TEST_PRESETS)
    assert result.pack is None and [i.code for i in result.issues] == ["TOML_SYNTAX"]


def _castle_text() -> str:
    return files("gumshoe.cases.packs").joinpath("castle.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("source", ["base", "castle"])
def test_a_misspelt_top_level_section_stops_the_pipeline_at_stage_1(source):
    if source == "base":
        result = load(BASE_TOML.replace("[roles.", "[rolse."))
    else:
        result = load_pack(_castle_text().replace("[roles.", "[rolse.").encode())
    assert result.pack is None
    assert [(i.code, i.path) for i in result.issues] == [("UNKNOWN_KEY", "rolse")]
    assert {i.stage for i in result.issues} == {1}


def test_an_unknown_meta_key_is_reported_under_meta_and_is_not_flattened():
    for extra in ('record_kinds = ["ghost"]', "roles = 7", 'author = "x"'):
        text = replace('id = "tiny"\n', f'id = "tiny"\n{extra}\n')(BASE_TOML)
        key = extra.split(" ")[0]
        result = load(text)
        assert result.pack is None, extra
        assert [(i.code, i.path) for i in result.issues] == [("UNKNOWN_KEY", f"meta.{key}")]
        assert "known: id, presets, skeleton_rev, skin_rev, slots" in result.issues[0].suggestion


def test_an_unknown_meta_key_gets_a_did_you_mean():
    text = replace("slots = 4\n", "slots = 4\nskin_revv = 2\n")(BASE_TOML)
    (issue,) = load(text).issues
    assert issue.path == "meta.skin_revv"
    assert issue.suggestion.startswith("did you mean 'skin_rev'?")


def test_reshape_keeps_only_the_meta_fields():
    out = reshape({"meta": {"id": "x", "roles": 7, "record_kinds": ["ghost"]}})
    assert out == {"id": "x"}


def test_a_meta_that_is_not_a_table_is_a_wrong_type_at_meta():
    result = load("meta = 5\n[capacity]" + BASE_TOML.split("[capacity]", 1)[1])
    assert result.pack is None
    assert ("WRONG_TYPE", "meta") in [(i.code, i.path) for i in result.issues]


@pytest.mark.parametrize("value", ["5", "[1, 2]"])
def test_a_keyed_section_of_the_wrong_shape_is_a_wrong_type_not_a_crash(value):
    roles = BASE_TOML.index("[roles.maid]")
    scenes = BASE_TOML.index("[scene_types.study_murder]")
    text = f"roles = {value}\n" + BASE_TOML[:roles] + BASE_TOML[scenes:]
    result = load(text)
    assert result.pack is None
    assert [(i.code, i.path) for i in result.issues] == [("WRONG_TYPE", "roles")]
