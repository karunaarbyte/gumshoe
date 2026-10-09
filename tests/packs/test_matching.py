import time
from importlib.resources import files
from math import comb, perm

import pytest

from gumshoe.cases.model.pack import Capacity, MotiveDef, Pack, RoleDef
from gumshoe.cases.model.spec import PRESETS
from gumshoe.cases.packs.check import capacity, matching
from gumshoe.cases.packs.loader import load_pack
from gumshoe.cases.packs.runner import check_pack
from tests.packs.fixtures import BASE_TOML, CAPACITY, TEST_PRESETS, preset, rich_pack, scenes
from tests.packs.mutations import MUTATIONS


def test_matchings_enumerates_distinct_assignments_in_sorted_order():
    allowed = {"a": ("x", "y"), "b": ("x", "y")}
    assert list(matching.matchings(allowed, ("a", "b"))) == [("x", "y"), ("y", "x")]
    assert list(matching.matchings({"a": ("x",), "b": ("x",)}, ("a", "b"))) == []
    assert list(matching.matchings({}, ())) == [()]


def _pack(allowed: dict[str, tuple[str, ...]], preset="tiny", suspects=3):
    motives = sorted({m for v in allowed.values() for m in v})
    return rich_pack(
        presets=(preset,),
        capacity=Capacity(
            max_suspects=suspects, max_locations=3, max_methods=3, max_record_kinds=2
        ),
        scene_types=scenes(3),
        roles=tuple(
            RoleDef(key=k, record_kinds=("ledger",), motive_types=v) for k, v in allowed.items()
        ),
        motive_defs=tuple(MotiveDef(key=m, label=m) for m in motives),
    )


def found(pack):
    return [(i.code, i.path) for i in matching.check(pack, TEST_PRESETS)]


def test_a_fair_roster_passes():
    pack = _pack({"a": ("x", "y", "z"), "b": ("x", "y", "z"), "c": ("x", "y", "z")})
    assert found(pack) == []  # every (role, motive) share is a third


def test_a_forced_assignment_is_too_predictable_and_names_role_motive_and_roster():
    # four suspects over four motive types; only d allows z, so d always gets z
    pack = _pack(
        {"a": ("w", "x", "y"), "b": ("w", "x", "y"), "c": ("w", "x", "y"), "d": ("x", "y", "z")},
        preset="quad",
        suspects=4,
    )
    got = [(i.code, i.path, i.message) for i in matching.check(pack, TEST_PRESETS)]
    assert [(c, p) for c, p, _ in got] == [("MOTIVE_TOO_PREDICTABLE", "roles.d.motive_types[z]")]
    assert "100%" in got[0][2] and "a,b,c,d" in got[0][2]


def test_a_roster_with_too_few_motive_types_has_no_perfect_matching():
    # a, b, c, d all share three motive types, so that roster of four cannot be matched
    shared = ("x", "y", "z")
    pack = _pack(
        {"a": shared, "b": shared, "c": shared, "d": shared, "e": ("w", "x", "y")}, "quad", 4
    )
    issues = matching.check(pack, TEST_PRESETS)
    assert [i.message for i in issues if i.code == "NO_PERFECT_MATCHING"] == [
        "no suspect-to-motive matching exists for roster a,b,c,d"
    ]


def test_unhosted_presets_are_skipped_not_double_reported():
    assert found(rich_pack(presets=("huge",))) == []


def test_the_castle_scale_enumeration_is_fast_enough():
    motives = tuple(f"m{i}" for i in range(8))
    allowed = {f"r{r}": tuple(motives[(r + j) % 8] for j in range(8)) for r in range(8)}
    start = time.perf_counter()
    total = sum(1 for _ in matching.matchings(allowed, tuple(sorted(allowed))[:7]))
    assert total == 40320 and time.perf_counter() - start < 5


def test_a_pack_with_no_roles_has_nothing_to_match():
    assert found(Pack(id="e", capacity=CAPACITY, presets=("tiny",))) == []


def test_no_perfect_matching_is_reported_at_most_five_times_per_suspect_count():
    # 15 rosters of four drawn from a..f share three motive types and cannot be matched
    shared: tuple[str, ...] = ("x", "y", "z")
    allowed = {k: shared for k in "abcdef"} | {"g": ("w", "x", "y")}
    issues = matching.check(_pack(allowed, "quad", 4), TEST_PRESETS)
    failing = [i.message.rsplit(" ", 1)[1] for i in issues if i.code == "NO_PERFECT_MATCHING"]
    assert failing == ["a,b,c,d", "a,b,c,e", "a,b,c,f", "a,b,d,e", "a,b,d,f"]


def _wide_pack(roles: int, motives: int, suspects: int) -> Pack:
    """The base pack with `roles` roles that each allow all `motives` motive types."""
    base = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    assert base is not None
    keys = tuple(f"m{i}" for i in range(motives))
    return base.model_copy(
        update={
            "presets": ("big",),
            "capacity": base.capacity.model_copy(update={"max_suspects": suspects}),
            "roles": tuple(
                RoleDef(
                    key=f"r{i:02}",
                    noun=f"n{i:02}",
                    record_kinds=("ledger",),
                    motive_types=keys,
                    style="calm",
                )
                for i in range(roles)
            ),
            "motive_defs": tuple(
                MotiveDef(key=k, label=f"motive {k}", hints=base.motive_defs[0].hints) for k in keys
            ),
        }
    )


def test_a_matching_check_over_the_budget_is_an_unsupported_preset_and_is_fast():
    presets = {"big": preset("big", 7, 3)}
    start = time.perf_counter()
    issues = check_pack(_wide_pack(12, 8, 7), presets)
    elapsed = time.perf_counter() - start
    (issue,) = [i for i in issues if 6 <= i.stage <= 7]
    assert (issue.code, issue.path) == ("PRESET_UNSUPPORTED", "meta.presets[big]")
    bound = comb(12, 7) * perm(8, 7)
    assert (
        f"matching check too large (roles=12, motive types=8, up to {bound} matchings;"
        " the limit is 5000000)"
    ) in issue.message
    assert elapsed < 2, elapsed


def test_the_budget_is_five_million_and_the_castle_is_well_inside_it():
    assert capacity.MATCHING_BUDGET == 5_000_000
    castle = files("gumshoe.cases.packs").joinpath("castle.toml").read_bytes()
    pack = load_pack(castle).pack
    assert pack is not None
    bounds = [
        capacity.matching_bound(pack, spec.suspects)
        for _, spec in capacity.hosted_specs(pack, PRESETS)
    ]
    assert len(bounds) == 3 and max(bounds) <= capacity.MATCHING_BUDGET


@pytest.mark.parametrize("code", ["MOTIVE_TOO_PREDICTABLE", "NO_PERFECT_MATCHING"])
def test_a_pack_just_inside_the_budget_is_still_enumerated_exactly(monkeypatch, code):
    pack = load_pack(MUTATIONS[code].apply(BASE_TOML).encode(), TEST_PRESETS).pack
    assert pack is not None
    before = check_pack(pack, TEST_PRESETS)
    bound = capacity.matching_bound(pack, 4)
    monkeypatch.setattr(capacity, "MATCHING_BUDGET", bound)
    assert check_pack(pack, TEST_PRESETS) == before
    monkeypatch.setattr(capacity, "MATCHING_BUDGET", bound - 1)
    after = [(i.code, i.path) for i in check_pack(pack, TEST_PRESETS) if 6 <= i.stage <= 7]
    assert after == [("PRESET_UNSUPPORTED", "meta.presets[quad]")]
