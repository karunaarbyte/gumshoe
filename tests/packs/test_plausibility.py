from gumshoe.cases.model.pack import Pack, RoleDef, SceneType, SlotDef
from gumshoe.cases.packs.check import plausibility
from tests.packs.fixtures import CAPACITY, rich_pack


def found(pack):
    return [(i.code, i.path) for i in plausibility.check(pack)]


def _scene(**changes):
    fields = {
        "key": "s",
        "location_kinds": ("study",),
        "allowed_methods": ("poison",),
        "allowed_trace_kinds": ("residue",),
    }
    fields.update(changes)
    return SceneType(**fields)


def test_every_role_needs_three_motive_types_and_a_record_kind():
    role = RoleDef(key="r", record_kinds=(), motive_types=("debt", "debt"))
    got = found(rich_pack(roles=(role,)))
    assert ("ROLE_NO_RECORD_KIND", "roles.r.record_kinds") in got
    assert ("ROLE_TOO_FEW_MOTIVES", "roles.r.motive_types") in got  # two entries, one distinct


def test_a_motive_type_no_role_allows_is_unreachable():
    got = found(rich_pack())
    assert ("MOTIVE_UNREACHABLE", "motive_defs.debt") not in got
    role = rich_pack().roles[0].model_copy(update={"motive_types": ()})
    assert ("MOTIVE_UNREACHABLE", "motive_defs.debt") in found(rich_pack(roles=(role,)))


def test_a_method_must_be_allowed_in_two_scene_types():
    one = rich_pack(scene_types=(_scene(),))
    assert ("METHOD_TOO_RARE", "method_defs.poison") in found(one)
    two = rich_pack(scene_types=(_scene(key="a"), _scene(key="b")))
    assert ("METHOD_TOO_RARE", "method_defs.poison") not in found(two)


def test_a_scene_without_a_crime_location_does_not_also_report_impossible_methods():
    got = found(rich_pack(scene_types=(_scene(location_kinds=()), _scene(key="b"))))
    assert ("SCENE_NO_CRIME_LOCATION", "scene_types.s.location_kinds") in got
    assert not [c for c, _ in got if c == "SCENE_METHOD_IMPOSSIBLE"]


def test_a_method_with_no_placeable_trace_is_impossible_at_that_scene():
    scenes = (_scene(key="a"), _scene(key="b", allowed_trace_kinds=("fibre",)))
    assert ("SCENE_METHOD_IMPOSSIBLE", "scene_types.b.allowed_methods[poison]") in found(
        rich_pack(scene_types=scenes)
    )
    elsewhere = (_scene(key="a"), _scene(key="b", location_kinds=("garden",)))
    assert ("SCENE_METHOD_IMPOSSIBLE", "scene_types.b.allowed_methods[poison]") in found(
        rich_pack(scene_types=elsewhere)
    )


def test_slot_definitions_must_cover_the_slot_count():
    pack = rich_pack(slots=4, slot_defs=(SlotDef(key="a", at="at a", during="during a"),))
    assert ("SLOT_DEFS_TOO_FEW", "slot_defs") in found(pack)


def test_an_empty_pack_reports_only_its_missing_slot_definitions():
    got = [c for c, _ in found(Pack(id="e", capacity=CAPACITY))]
    assert got == ["SLOT_DEFS_TOO_FEW"]
