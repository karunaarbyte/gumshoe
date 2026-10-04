import pytest

from gumshoe.cases.generate.gen_context import GenContext
from tests.generate.helpers import PRESET_NAMES, SEEDS, castle, stages


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_contract_e_the_timeline_table_and_the_opportunity_count(preset):
    pack = castle()
    records = {d.key: d for d in pack.record_defs}
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        _, truth, timeline = stages(ctx)
        roster, spec = truth.roster, ctx.spec
        positions = {loc.pos for loc in roster.locations}
        kind = {loc.pos: loc.kind for loc in roster.locations}
        assert 1 <= timeline.crime_slot <= spec.slots - 2
        assert [row.suspect_pos for row in timeline.rows] == [s.pos for s in roster.suspects]
        for row in timeline.rows:  # one place per suspect per slot, so no double-booking
            assert len(row.places) == spec.slots and set(row.places) <= positions
        crime = timeline.crime_slot
        rows = {row.suspect_pos: row for row in timeline.rows}
        assert rows["s0"].places[crime] == "l0"  # the culprit is at the scene
        at_scene = [s.pos for s in roster.suspects[1:] if rows[s.pos].places[crime] == "l0"]
        assert len(at_scene) == spec.opportunity and set(at_scene) == set(timeline.opportunity)
        # (b') everyone else is at a non-scene place their own record kind attests
        for s in roster.suspects[1:]:
            if s.pos not in at_scene:
                place = rows[s.pos].places[crime]
                assert place != "l0"
                assert kind[place] in records[s.record_kind].location_kinds


def test_the_crime_slot_takes_both_inner_values_and_places_vary():
    pack = castle()
    slots, places = set(), set()
    for seed in SEEDS:
        _, _, timeline = stages(GenContext.of(pack, seed, "standard"))
        slots.add(timeline.crime_slot)
        places |= {p for row in timeline.rows for p in row.places}
    assert slots == {1, 2} and len(places) >= 5


def test_the_stage_is_deterministic_and_does_not_change_the_truth_it_reads():
    ctx = GenContext.of(castle(), 3, "long")
    _, truth_a, a = stages(ctx)
    _, truth_b, b = stages(ctx)
    assert a == b and a.digest() == b.digest() and truth_a == truth_b
