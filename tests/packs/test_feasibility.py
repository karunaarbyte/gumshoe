import time

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS
from gumshoe.cases.packs.check import feasibility
from gumshoe.cases.packs.check.capacity import hosted_specs
from gumshoe.cases.packs.check.depths import feasible_depths
from gumshoe.cases.packs.check.feasibility import (
    ROSTER_CHECK_BUDGET,
    holder_assignments,
    reachable_location_records,
    walk,
)
from gumshoe.cases.packs.loader import load_pack
from gumshoe.cases.tools.builtin import load_builtin_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS


def test_reachable_location_records_for_the_base_pack():
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    # one suspect kind (ledger) and one place kind (gate_log); two record kinds are drawn,
    # so exactly one of them is about a place
    assert list(reachable_location_records(pack, 2)) == [1]


def test_the_castle_walk_is_feasible_and_cheap():
    pack = load_builtin_pack("castle")
    started = time.perf_counter()
    for name, spec in hosted_specs(pack, PRESETS):
        result = walk(pack, name, spec, ROSTER_CHECK_BUDGET)
        assert result.failures == [] and not result.over_budget, (name, result.failures[:3])
        assert result.draws > 0
    assert time.perf_counter() - started < 5


def test_a_draw_is_one_scene_roles_record_kinds_secret_kinds_and_methods():
    # the unit of the count, pinned: one draw per (scene, roles, record-kind subset with
    # holders, secret-kind set, method subset); placement checks count against the budget only
    pack = load_builtin_pack("castle")
    counts = {
        name: walk(pack, name, spec, ROSTER_CHECK_BUDGET).draws
        for name, spec in hosted_specs(pack, PRESETS)
    }
    assert counts == {"short": 5950, "standard": 2429, "long": 72}


def test_a_walk_over_its_budget_stops_and_the_preset_is_unsupported(monkeypatch):
    pack = load_builtin_pack("castle")
    spec = dict(hosted_specs(pack, PRESETS))["standard"]
    result = walk(pack, "standard", spec, 1)
    assert result.over_budget and result.failures == []
    monkeypatch.setattr(feasibility, "ROSTER_CHECK_BUDGET", 1)
    issues = feasibility.check(pack, PRESETS)
    assert {i.code for i in issues} == {"PRESET_UNSUPPORTED"}
    assert sorted(i.path for i in issues) == [
        "meta.presets[long]",
        "meta.presets[short]",
        "meta.presets[standard]",
    ]
    assert all("roster check too large (more than 1 draws)" in i.message for i in issues)


def test_holder_assignments_gives_each_kind_a_distinct_role_that_lists_it():
    assert list(holder_assignments([], [["a"], ["b"]])) == [{}]
    assert list(holder_assignments(["a"], [["a"], ["b"], ["a", "b"]])) == [{0: "a"}, {2: "a"}]
    assert list(holder_assignments(["a", "b"], [["a", "b"], ["a", "b"]])) == [
        {0: "a", 1: "b"},
        {1: "a", 0: "b"},
    ]
    assert list(holder_assignments(["a", "b"], [["a", "b"], ["c"]])) == []
    assert list(holder_assignments(["c"], [["a"], ["b"]])) == []


def _castle_with(change):
    data = load_builtin_pack("castle").model_dump(mode="json")
    change(data)
    return Pack.model_validate(data)


def _narrow_trace(method, kinds):
    def change(data):
        (m,) = [m for m in data["method_defs"] if m["key"] == method]
        m["traces"][0]["location_kinds"] = kinds

    return change


def test_a_method_with_no_non_scene_place_at_a_scene_is_reported():
    pack = _castle_with(_narrow_trace("dagger", ["chapel"]))
    spec = dict(hosted_specs(pack, PRESETS))["short"]
    result = walk(pack, "short", spec, ROSTER_CHECK_BUDGET)
    assert len(result.failures) == 5  # capped
    assert all(
        r.startswith("scene murder_in_chapel, roles ")
        and "dagger" in r
        and r.endswith(": no set of locations satisfies the trace and record constraints")
        for r in result.failures
    )
    issues = [i for i in feasibility.check(pack, PRESETS) if i.code == "ROSTER_INFEASIBLE"]
    assert {i.path for i in issues} >= {"meta.presets[short]"}
    assert len([i for i in issues if i.path == "meta.presets[short]"]) == 5
    assert issues[0].message.startswith(
        "the 'short' preset can draw a roster the generator cannot build: scene murder_in_chapel"
    )


def test_roles_with_no_record_kind_set_are_reported():
    def suspect_gate_log(data):
        (r,) = [r for r in data["record_defs"] if r["key"] == "gate_log"]
        r["subject"] = "suspect"

    pack = _castle_with(suspect_gate_log)
    spec = dict(hosted_specs(pack, PRESETS))["short"]
    result = walk(pack, "short", spec, ROSTER_CHECK_BUDGET)
    assert result.failures
    assert all(
        r.endswith(": no record-kind set gives every role a kind and every kind a holder")
        for r in result.failures
    )


def test_a_record_kind_set_with_no_gating_depth_is_reported():
    # three suspects and methods at a 12% decisive share: depth 2 needs one location record
    # (300 <= 12 x 25), so the two suspect-subject kinds together leave no depth
    pack = load_builtin_pack("castle")
    spec = dict(hosted_specs(pack, PRESETS))["short"].model_copy(
        update={"suspects": 3, "motives": 3, "methods": 3}
    )
    spec = spec.model_copy(
        update={"limits": spec.limits.model_copy(update={"decisive_pct_max": 12})}
    )
    assert feasible_depths(spec, 0) == [] and feasible_depths(spec, 1) == [2]
    result = walk(pack, "short", spec, ROSTER_CHECK_BUDGET)
    assert result.failures
    assert all(
        "record kinds chapel_register+visitor_ledger" in r
        and r.endswith(": no gating depth fits 0 location-subject record kinds")
        for r in result.failures
    )


def test_a_preset_with_no_depth_at_all_is_not_walked():
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack.model_copy(
        update={"presets": ("nodepth",)}
    )
    assert [i.code for i in feasibility.check(pack, TEST_PRESETS)] == ["PRESET_NO_DEPTH"]
