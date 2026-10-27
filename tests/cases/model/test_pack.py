import pytest
from pydantic import ValidationError

from gumshoe.cases.model.pack import Capacity, Pack, RoleDef, SceneType
from tests.generate.helpers import castle


def make_pack(**overrides):
    base = dict(
        id="tiny",
        capacity=Capacity(max_suspects=3, max_locations=3, max_methods=3, max_record_kinds=2),
        scene_types=(
            SceneType(
                key="study_murder",
                location_kinds=("study",),
                allowed_methods=("rope", "dagger", "poison"),
                allowed_trace_kinds=("residue",),
            ),
        ),
        roles=(
            RoleDef(
                key="cook",
                record_kinds=("ledger",),
                motive_types=("jealousy", "debt", "inheritance"),
            ),
        ),
        record_kinds=("ledger", "gate_log"),
    )
    base.update(overrides)
    return Pack(**base)


def test_defaults_and_sorting():
    pack = make_pack()
    assert pack.skeleton_rev == 1 and pack.skin_rev == 1 and pack.slots == 4
    assert pack.record_kinds == ("gate_log", "ledger")
    assert pack.scene_types[0].allowed_methods == ("dagger", "poison", "rope")
    assert pack.roles[0].motive_types == ("debt", "inheritance", "jealousy")


def test_skeleton_hash_is_stable_hex():
    first = make_pack().skeleton_hash()
    assert first == make_pack().skeleton_hash()
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")


def test_skeleton_hash_ignores_skin_rev_and_input_order():
    assert make_pack().skeleton_hash() == make_pack(skin_rev=9).skeleton_hash()
    assert (
        make_pack().skeleton_hash()
        == make_pack(record_kinds=("gate_log", "ledger")).skeleton_hash()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"id": "other"},
        {"skeleton_rev": 2},
        {"slots": 5},
        {"capacity": Capacity(max_suspects=4, max_locations=3, max_methods=3, max_record_kinds=2)},
        {"record_kinds": ("ledger",)},
    ],
)
def test_skeleton_hash_changes_with_any_structural_edit(change):
    assert make_pack().skeleton_hash() != make_pack(**change).skeleton_hash()


def test_pack_is_frozen_and_rejects_negative_capacity():
    with pytest.raises(ValidationError):
        make_pack().id = "x"
    with pytest.raises(ValidationError):
        Capacity(max_suspects=-1, max_locations=1, max_methods=1, max_record_kinds=1)


def test_pack_rejects_non_positive_revisions_and_slots():
    for bad in ({"slots": 0}, {"skeleton_rev": 0}, {"skin_rev": 0}):
        with pytest.raises(ValidationError):
            make_pack(**bad)


def test_pack_rejects_duplicate_scene_or_role_keys():
    scene = SceneType(key="dup")
    role = RoleDef(key="dup")
    with pytest.raises(ValidationError, match="duplicate"):
        make_pack(scene_types=(scene, scene))
    with pytest.raises(ValidationError, match="duplicate"):
        make_pack(roles=(role, role))


def test_a_preposition_is_wording_so_it_never_changes_the_skeleton_hash():
    pack = castle()
    first = pack.location_defs[0]
    changed = first.model_copy(
        update={"names": tuple(e.model_copy(update={"prep": "on"}) for e in first.names)}
    )
    other = pack.model_copy(update={"location_defs": (changed, *pack.location_defs[1:])})
    assert other.skeleton_hash() == pack.skeleton_hash()


def test_the_castle_skeleton_hash_is_pinned():
    assert castle().skeleton_hash() == (
        "b4bc72f6e36be40c4baa3cb59bd3d29ac22cfbb1dfafb80c10a6f9b160408e4a"
    )
