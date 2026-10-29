"""What belongs to the castle alone: its exact counts, its pinned names and revisions.

The rules every setting must meet run on every bundled pack in `test_bundled_packs.py`.
"""

import tomllib
from importlib.resources import files

import pytest

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, derive_spec
from gumshoe.cases.packs import LoadResult, load_pack
from gumshoe.cases.packs.check.capacity import hosting_scenes
from gumshoe.cases.tools.builtin import load_builtin_pack


def _castle_bytes() -> bytes:
    return files("gumshoe.cases.packs").joinpath("castle.toml").read_bytes()


def _castle() -> LoadResult:
    return load_pack(_castle_bytes())


@pytest.fixture
def pack() -> Pack:
    loaded = _castle().pack
    assert loaded is not None
    return loaded


def test_the_castle_loads_with_no_issues_under_the_real_presets():
    result = _castle()
    assert [(i.code, i.path) for i in result.issues] == [] and result.pack is not None


def test_the_castle_resource_is_found_by_the_builtin_loader():
    assert load_builtin_pack("castle").id == "castle"


def test_the_castle_meets_the_spec_counts(pack):
    assert len(pack.roles) >= 8 and len(pack.motive_defs) >= 8
    assert len(pack.location_defs) >= 7 and len(pack.method_defs) >= 6
    assert len(pack.record_defs) >= 3 and len(pack.families) >= 12


def test_the_castle_claims_exactly_three_presets_and_fits_its_capacity_in_its_pools(pack):
    assert set(pack.presets) == {"short", "standard", "long"}
    cap = pack.capacity
    assert cap.max_locations <= len(pack.location_defs)
    assert cap.max_methods <= len(pack.method_defs)
    assert cap.max_record_kinds <= len(pack.record_defs)
    assert cap.max_suspects <= len(pack.roles) and cap.max_suspects <= len(pack.motive_defs)


def test_the_castle_toml_text_matches_the_loaded_pack_for_its_role_keys(pack):
    raw = tomllib.loads(_castle_bytes().decode())
    assert set(raw["roles"]) == {r.key for r in pack.roles}


def test_the_household_register_attests_every_room_and_the_gate_log_only_the_gatehouse(pack):
    records = {d.key: d for d in pack.record_defs}
    assert set(records["chapel_register"].location_kinds) == {d.key for d in pack.location_defs}
    assert records["chapel_register"].names[0].text == "household register"
    assert records["gate_log"].location_kinds == ("gatehouse",)


def test_the_skin_revision_moved_with_the_new_wording(pack):
    assert pack.skin_rev >= 2


def test_the_victims_are_lords_with_a_title_and_a_pronoun(pack):
    assert len(pack.victims) >= 6
    for victim in pack.victims:
        assert victim.text.startswith("Lord ") and victim.pronoun == "he" and victim.proper
    assert len({v.text for v in pack.victims}) == len(pack.victims)


def test_the_castle_hosting_scenes_per_preset_do_not_fall():
    pack = load_builtin_pack("castle")
    expected_minimum = {"short": 7, "standard": 7, "long": 4}  # measured: 7, 7, 4
    for name in pack.presets:
        spec = derive_spec(name, pack, PRESETS)
        assert len(hosting_scenes(pack, spec)) >= expected_minimum[name], name  # long was once one


def test_the_castle_has_sixteen_distinct_role_names(pack):
    names = [e.text for r in pack.roles for e in r.names]
    assert len(names) == 16 and len(set(names)) == len(names)
