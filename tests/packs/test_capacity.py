from gumshoe.cases.model.pack import Capacity, MotiveDef, Pack, RoleDef
from gumshoe.cases.packs.check import capacity
from tests.packs.fixtures import CAPACITY, TEST_PRESETS, rich_pack


def found(pack, presets=TEST_PRESETS):
    return [(i.code, i.path) for i in capacity.check(pack, presets)]


def _roles(n):
    return tuple(RoleDef(key=f"r{i}", motive_types=("a", "b", "c")) for i in range(n))


def _hostable(**changes):
    """Three roles and three motive types, so a three-suspect preset can be hosted."""
    fields = {
        "roles": _roles(3),
        "motive_defs": tuple(MotiveDef(key=k, label=k) for k in ("a", "b", "c")),
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
        capacity=Capacity(max_suspects=2, max_locations=1, max_methods=3, max_record_kinds=2),
    )
    (issue,) = capacity.check(small, TEST_PRESETS)
    assert "suspects=2" in issue.message and "locations=1" in issue.message


def test_a_preset_needs_as_many_roles_and_motive_types_as_suspects():
    few_roles = rich_pack(presets=("tiny",), roles=_roles(2))
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
