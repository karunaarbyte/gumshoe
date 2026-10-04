import pytest
from pydantic import ValidationError

from gumshoe.cases.model.entities import Limits, Spec
from gumshoe.cases.model.pack import Capacity, Pack
from gumshoe.cases.model.spec import (
    PRESET_ORDER,
    PRESETS,
    PresetDef,
    SizeRange,
    UnsupportedPreset,
    check_presets,
    derive_spec,
    supported_presets,
)


def pack(**caps):
    base = dict(max_suspects=8, max_locations=7, max_methods=6, max_record_kinds=3)
    base.update(caps)
    return Pack(id="castle", slots=4, capacity=Capacity(**base))


def test_preset_table_matches_the_spec():
    assert PRESET_ORDER == ("short", "standard", "long")
    short, standard, long = (PRESETS[n] for n in PRESET_ORDER)
    assert (short.suspects, short.methods, short.locations) == (
        SizeRange(min=4, max=4),
        SizeRange(min=3, max=3),
        SizeRange(min=3, max=3),
    )
    assert (standard.suspects, standard.methods, standard.locations) == (
        SizeRange(min=5, max=5),
        SizeRange(min=4, max=4),
        SizeRange(min=4, max=5),
    )
    assert (long.suspects, long.methods, long.locations) == (
        SizeRange(min=7, max=7),
        SizeRange(min=5, max=5),
        SizeRange(min=6, max=6),
    )
    assert [PRESETS[n].record_kinds for n in PRESET_ORDER] == [
        SizeRange(min=2, max=2),
        SizeRange(min=2, max=2),
        SizeRange(min=3, max=3),
    ]


def test_builtin_presets_are_monotone_and_non_overlapping():
    assert check_presets(PRESETS) == []


def test_check_presets_reports_overlap_and_non_monotone_limits():
    base = PRESETS["standard"]
    overlapping = {
        **PRESETS,
        "standard": base.model_copy(update={"suspects": SizeRange(min=4, max=5)}),
    }
    assert any("overlap" in p and "suspects" in p for p in check_presets(overlapping))
    weaker = base.limits.model_copy(update={"solution_min": 1})
    non_monotone = {**PRESETS, "standard": base.model_copy(update={"limits": weaker})}
    assert any("monotone" in p and "solution_min" in p for p in check_presets(non_monotone))
    harder_share = base.limits.model_copy(update={"decisive_pct_max": 90})
    assert any(
        "decisive_pct_max" in p
        for p in check_presets(
            {**PRESETS, "standard": base.model_copy(update={"limits": harder_share})}
        )
    )


def test_derive_spec_uses_the_effective_sizes_and_the_preset_limits():
    spec = derive_spec("standard", pack())
    assert (spec.preset, spec.suspects, spec.methods, spec.motives) == ("standard", 5, 4, 5)
    assert (spec.locations, spec.record_kinds, spec.slots) == (5, 2, 4)
    assert spec.limits == PRESETS["standard"].limits and spec.source_cap == 4


def test_effective_size_is_capped_by_the_pack_but_must_reach_the_minimum():
    hut = pack(max_suspects=5, max_locations=4, max_record_kinds=2)
    assert derive_spec("standard", hut).locations == 4  # standard accepts 4..5
    assert derive_spec("short", hut).suspects == 4
    with pytest.raises(UnsupportedPreset, match="long.*suspects"):
        derive_spec("long", hut)


def test_supported_presets_lists_exactly_what_the_pack_can_host():
    hut = pack(max_suspects=5, max_locations=4, max_record_kinds=2)
    assert supported_presets(hut) == ("short", "standard")
    assert supported_presets(pack()) == ("short", "standard", "long")


def test_unknown_preset_and_short_slot_count_are_unsupported():
    with pytest.raises(UnsupportedPreset, match="unknown"):
        derive_spec("epic", pack())
    few = Pack(
        id="p",
        slots=3,
        capacity=Capacity(max_suspects=8, max_locations=7, max_methods=6, max_record_kinds=3),
    )
    with pytest.raises(UnsupportedPreset, match="slots"):
        derive_spec("short", few)


def test_custom_preset_tables_are_accepted():
    tiny = PresetDef(
        name="tiny",
        suspects=SizeRange(min=3, max=3),
        methods=SizeRange(min=3, max=3),
        locations=SizeRange(min=3, max=3),
        record_kinds=SizeRange(min=2, max=2),
        slots=4,
        opportunity=1,
        limits=Limits(
            solution_min=3,
            solution_max=12,
            depth_min=0,
            depth_max=3,
            actions_min=2,
            actions_max=8,
            decisive_pct_max=30,
        ),
    )
    p = Pack(
        id="tiny",
        capacity=Capacity(max_suspects=3, max_locations=3, max_methods=3, max_record_kinds=2),
    )
    assert derive_spec("tiny", p, {"tiny": tiny}).suspects == 3


def test_size_range_rejects_min_above_max():
    with pytest.raises(ValueError, match="min"):
        SizeRange(min=5, max=3)


def test_slots_are_pack_declared():
    six = Pack(
        id="p",
        slots=6,
        capacity=Capacity(max_suspects=8, max_locations=7, max_methods=6, max_record_kinds=3),
    )
    assert derive_spec("short", six).slots == 6


def test_the_presets_set_the_opportunity_count_one_two_three():
    assert [PRESETS[n].opportunity for n in ("short", "standard", "long")] == [1, 2, 3]


def test_derive_spec_copies_the_presets_opportunity():
    assert [derive_spec(n, pack()).opportunity for n in ("short", "standard", "long")] == [1, 2, 3]


def test_opportunity_must_leave_a_culprit_and_cannot_be_negative():
    fields = PRESETS["short"].model_dump()
    with pytest.raises(ValidationError, match="smallest suspect count"):
        PresetDef(**{**fields, "opportunity": 4})  # suspects.min is 4: at most 3 wrong suspects
    with pytest.raises(ValidationError, match="smallest suspect count"):
        PresetDef(**{**fields, "opportunity": -1})
    assert PresetDef(**{**fields, "opportunity": 0}).opportunity == 0
    assert PresetDef(**{**fields, "opportunity": 3}).opportunity == 3


def test_a_spec_cannot_carry_a_negative_opportunity():
    spec = derive_spec("short", pack())
    with pytest.raises(ValidationError):
        Spec(**{**spec.model_dump(), "opportunity": -1})
