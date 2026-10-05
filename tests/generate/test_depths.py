import pytest

from gumshoe.cases.generate.facts import feasible_depths
from gumshoe.cases.model.spec import PRESETS, derive_spec
from tests.generate.helpers import castle


def castle_spec(preset, locations=None):
    spec = derive_spec(preset, castle(), PRESETS)
    return spec if locations is None else spec.model_copy(update={"locations": locations})


@pytest.mark.parametrize(
    "preset, depths",
    [("short", [0, 1]), ("standard", [0, 1, 2]), ("long", [2])],
)
def test_the_castle_feasible_depths_per_preset(preset, depths):
    assert feasible_depths(castle_spec(preset), location_records=1) == depths


def test_short_loses_depth_2_to_search_capacity_and_long_needs_it_for_the_windows():
    short = castle_spec("short")
    assert 2 * short.methods + short.suspects == 10 > 9  # search demand against floor(0.8 * 4 * 3)
    assert 2 not in feasible_depths(short, location_records=0)
    long = castle_spec("long")
    assert feasible_depths(long, 0) == [2]  # depths 0 and 1 miss the size and depth windows


def test_standard_loses_depth_2_with_four_locations():
    assert feasible_depths(castle_spec("standard", locations=4), 1) == [0, 1]  # 13 against 12


def test_a_source_cap_below_three_or_a_window_that_fits_no_depth_gives_an_empty_set():
    standard = castle_spec("standard")
    small_sources = standard.model_copy(update={"source_cap": 2})
    assert feasible_depths(small_sources, 0) == []  # a record holds three facts
    narrow = standard.model_copy(
        update={"limits": standard.limits.model_copy(update={"solution_max": 3})}
    )
    assert feasible_depths(narrow, 0) == []  # every depth needs at least 4 facts


def test_depth_2_needs_room_for_a_five_action_solution():
    standard = castle_spec("standard")
    tight = standard.model_copy(
        update={"limits": standard.limits.model_copy(update={"actions_max": 4})}
    )
    assert feasible_depths(tight, 0) == [0, 1]  # the key may sit at a third location


def test_a_depth_is_dropped_when_the_decisive_facts_exceed_their_share():
    standard = castle_spec("standard")
    strict = standard.model_copy(
        update={"limits": standard.limits.model_copy(update={"decisive_pct_max": 8})}
    )
    # three decisive facts out of 33 (depth 0 and 1) or 38 (depth 2) with no location record
    assert feasible_depths(strict, 0) == [2]


def test_more_than_two_locations_per_method_is_never_feasible():
    standard = castle_spec("standard")  # four methods
    assert feasible_depths(standard.model_copy(update={"locations": 8}), 0) != []
    assert feasible_depths(standard.model_copy(update={"locations": 9}), 0) == []
