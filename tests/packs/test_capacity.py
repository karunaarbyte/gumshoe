from gumshoe.cases.model.pack import Capacity, MotiveDef, Pack, RoleDef, SceneType
from gumshoe.cases.model.spec import derive_spec
from gumshoe.cases.packs.check import capacity
from tests.packs.fixtures import CAPACITY, TEST_PRESETS, rich_pack, scenes


def found(pack, presets=TEST_PRESETS):
    return [(i.code, i.path) for i in capacity.check(pack, presets)]


def _roles(n):
    return tuple(
        RoleDef(key=f"r{i}", record_kinds=("ledger",), motive_types=("a", "b", "c"))
        for i in range(n)
    )


def _hostable(**changes):
    """Three roles and three motive types, so a three-suspect preset can be hosted."""
    fields = {
        "roles": _roles(3),
        "motive_defs": tuple(MotiveDef(key=k, label=k) for k in ("a", "b", "c")),
        "scene_types": scenes(3),
    }
    fields.update(changes)
    return rich_pack(**fields)


def test_a_pack_that_hosts_its_claimed_preset_has_no_issues():
    assert found(_hostable(presets=("tiny",))) == []


def test_an_unknown_preset_name_is_unsupported_with_the_reason():
    (issue,) = capacity.check(rich_pack(presets=("huge",)), TEST_PRESETS)
    assert issue.code == "PRESET_UNSUPPORTED" and issue.path == "meta.presets[huge]"
    assert "unknown preset" in issue.message


def test_capacity_below_a_preset_minimum_names_every_shortfall():
    small = rich_pack(
        presets=("tiny",),
        scene_types=scenes(3),
        capacity=Capacity(max_suspects=2, max_locations=1, max_methods=3, max_record_kinds=2),
    )
    (issue,) = capacity.check(small, TEST_PRESETS)
    assert "suspects=2" in issue.message and "locations=1" in issue.message


def test_a_preset_needs_as_many_roles_and_motive_types_as_suspects():
    few_roles = rich_pack(presets=("tiny",), roles=_roles(2), scene_types=scenes(3))
    (issue,) = capacity.check(few_roles, TEST_PRESETS)
    assert issue.code == "PRESET_UNSUPPORTED" and "roles=2" in issue.message


def test_effective_sizes_must_not_shrink_from_short_to_standard():
    pack = _hostable(presets=("short", "standard"))
    got = [(i.code, i.path, i.message) for i in capacity.check(pack, TEST_PRESETS)]
    assert any(c == "PRESET_NOT_MONOTONE" and p == "meta.presets[standard]" for c, p, _ in got)
    assert any("locations" in m for _, _, m in got)


def test_a_pack_claiming_nothing_has_nothing_to_check():
    assert found(Pack(id="e", capacity=CAPACITY)) == []


def test_presets_outside_the_preset_order_are_still_checked_without_raising():
    pack = _hostable(presets=("quad", "tiny"))
    assert [c for c, _ in found(pack)] == ["PRESET_UNSUPPORTED"]
    assert found(_hostable(presets=("tiny", "tiny"))) == []


def test_no_presets_table_reports_every_claim_as_unsupported():
    assert found(_hostable(presets=("tiny",)), {}) == [("PRESET_UNSUPPORTED", "meta.presets[tiny]")]


def _messages(pack):
    return [i.message for i in capacity.check(pack, TEST_PRESETS) if i.code == "PRESET_UNSUPPORTED"]


def test_two_scenes_that_can_host_the_methods_are_not_enough():
    (issue,) = capacity.check(_hostable(scene_types=scenes(2)), TEST_PRESETS)
    assert (issue.code, issue.path) == ("PRESET_UNSUPPORTED", "meta.presets[tiny]")
    assert "hosting scenes=2 (needs at least 3)" in issue.message


def test_three_scenes_that_can_host_the_methods_are_enough():
    assert found(_hostable(scene_types=scenes(3))) == []


def test_scenes_too_small_for_the_methods_do_not_count():
    two_big_one_small = scenes(2) + (SceneType(key="small", allowed_methods=("dagger", "poison")),)
    (message,) = _messages(_hostable(scene_types=two_big_one_small))
    assert "hosting scenes=2" in message


def test_a_method_listed_twice_in_a_scene_counts_once():
    doubled = tuple(
        SceneType(key=f"s{i}", allowed_methods=("dagger", "dagger", "poison")) for i in range(3)
    )
    (message,) = _messages(_hostable(scene_types=doubled))
    assert "hosting scenes=0 (needs at least 3)" in message


def test_methods_larger_than_every_scene_leave_a_count_of_zero():
    (message,) = _messages(_hostable(scene_types=scenes(4, ("dagger", "poison"))))
    assert "hosting scenes=0 (needs at least 3)" in message


def test_a_pack_with_no_scenes_is_unsupported_without_raising():
    (message,) = _messages(_hostable(scene_types=()))
    assert "hosting scenes=0" in message


def test_the_scene_reason_is_appended_to_the_other_reasons():
    pack = _hostable(roles=_roles(2), scene_types=scenes(2))
    (message,) = _messages(pack)
    assert "roles=2 (needs at least 3); hosting scenes=0 (needs at least 3)" in message


def test_a_record_kind_that_lists_only_the_scene_is_not_usable():
    ledger = rich_pack().record_defs[0].model_copy(update={"location_kinds": ("study",)})
    (message,) = _messages(_hostable(record_defs=(ledger,)))
    assert "hosting scenes=0 (needs at least 3)" in message


def test_a_location_subject_record_kind_never_makes_a_role_eligible():
    ledger = rich_pack().record_defs[0].model_copy(update={"subject": "location"})
    (message,) = _messages(_hostable(record_defs=(ledger,)))
    assert "hosting scenes=0 (needs at least 3)" in message


def test_scenes_with_enough_methods_but_too_few_eligible_roles_do_not_host():
    roles = (*_roles(2), RoleDef(key="r2", motive_types=("a", "b", "c")))  # r2: no record kind
    (message,) = _messages(_hostable(roles=roles))
    assert "hosting scenes=0 (needs at least 3)" in message


def test_the_shared_helpers_agree_with_the_rule():
    pack = _hostable()
    scene = pack.scene_types[0]
    assert capacity.eligible_roles(pack, scene) == ["r0", "r1", "r2"]
    assert capacity.usable_kind(pack.record_defs[0], scene) is True
    spec = derive_spec("tiny", pack, TEST_PRESETS)
    assert len(capacity.hosting_scenes(pack, spec)) == 3


def test_a_scene_without_location_kinds_hosts_nothing_and_never_raises():
    bare = SceneType(key="b", allowed_methods=("dagger", "poison", "rope"))
    assert capacity.eligible_roles(_hostable(scene_types=(bare,)), bare) == []


def test_a_role_naming_an_unknown_record_kind_is_not_eligible_and_never_raises():
    pack = _hostable()
    roles = tuple(r.model_copy(update={"record_kinds": ("nope",)}) for r in pack.roles)
    pack = pack.model_copy(update={"roles": roles})
    assert capacity.eligible_roles(pack, pack.scene_types[0]) == []


def test_capacity_above_the_pool_is_reported():
    pack = rich_pack().model_copy(
        update={"capacity": CAPACITY.model_copy(update={"max_suspects": 99})}
    )
    codes = [(i.code, i.path) for i in capacity.pool_problems(pack)]
    assert ("CAPACITY_EXCEEDS_POOL", "capacity.max_suspects") in codes


def test_fewer_than_three_location_kinds_is_reported():
    pack = rich_pack()  # two location kinds
    assert [i.code for i in capacity.pool_problems(pack)].count("LOCATION_KINDS_TOO_FEW") == 1
