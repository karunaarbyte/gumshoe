import time

from gumshoe.cases.model.pack import Capacity, MotiveDef, Pack, RoleDef
from gumshoe.cases.packs.check import matching
from tests.packs.fixtures import CAPACITY, TEST_PRESETS, rich_pack, scenes


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
