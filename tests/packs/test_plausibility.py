from gumshoe.cases.model.pack import Pack, RecordDef, RoleDef, SceneType, SlotDef
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


def _gate_log():
    return RecordDef(key="gate_log", subject="location", medium="written")


def _role_with(*kinds):
    return RoleDef(key="r", record_kinds=kinds, motive_types=("debt", "a", "b"))


def _record_pack(*kinds):
    base = rich_pack()
    return rich_pack(roles=(_role_with(*kinds),), record_defs=(*base.record_defs, _gate_log()))


def test_a_role_with_only_location_records_has_no_suspect_record():
    got = found(_record_pack("gate_log"))
    assert ("ROLE_NO_SUSPECT_RECORD", "roles.r.record_kinds") in got


def test_a_suspect_record_plus_a_location_record_is_enough():
    assert "ROLE_NO_SUSPECT_RECORD" not in [c for c, _ in found(_record_pack("ledger", "gate_log"))]


def test_a_role_with_no_record_kinds_reports_only_the_missing_kind():
    codes = [c for c, _ in found(_record_pack())]
    assert "ROLE_NO_RECORD_KIND" in codes
    assert "ROLE_NO_SUSPECT_RECORD" not in codes


def test_an_undefined_record_kind_is_not_about_a_suspect():
    got = found(_record_pack("nowhere"))
    assert ("ROLE_NO_SUSPECT_RECORD", "roles.r.record_kinds") in got


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
