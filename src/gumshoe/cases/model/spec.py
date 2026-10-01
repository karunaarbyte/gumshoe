"""Global presets and the derivation of a case spec from a preset and a pack."""

from collections.abc import Mapping
from typing import Self

from pydantic import Field, model_validator

from gumshoe.cases.model.entities import Frozen, Limits, Spec
from gumshoe.cases.model.pack import Pack


class SizeRange(Frozen):
    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min > self.max:
            raise ValueError("size range min must not exceed max")
        return self


class PresetDef(Frozen):
    name: str
    suspects: SizeRange
    methods: SizeRange
    locations: SizeRange
    record_kinds: SizeRange
    slots: int
    limits: Limits


class UnsupportedPreset(ValueError):
    """The pack cannot host this preset (or the preset does not exist)."""


def _limits(
    sol: tuple[int, int], depth: tuple[int, int], actions: tuple[int, int], pct: int
) -> Limits:
    return Limits(
        solution_min=sol[0],
        solution_max=sol[1],
        depth_min=depth[0],
        depth_max=depth[1],
        actions_min=actions[0],
        actions_max=actions[1],
        decisive_pct_max=pct,
    )


def _r(low: int, high: int) -> SizeRange:
    return SizeRange(min=low, max=high)


PRESET_ORDER = ("short", "standard", "long")

PRESETS: dict[str, PresetDef] = {
    "short": PresetDef(
        name="short",
        suspects=_r(4, 4),
        methods=_r(3, 3),
        locations=_r(3, 3),
        record_kinds=_r(2, 2),
        slots=4,
        limits=_limits((3, 14), (0, 2), (2, 8), 30),
    ),
    "standard": PresetDef(
        name="standard",
        suspects=_r(5, 5),
        methods=_r(4, 4),
        locations=_r(4, 5),
        record_kinds=_r(2, 2),
        slots=4,
        limits=_limits((4, 20), (1, 3), (3, 10), 25),
    ),
    "long": PresetDef(
        name="long",
        suspects=_r(7, 7),
        methods=_r(5, 5),
        locations=_r(6, 6),
        record_kinds=_r(3, 3),
        slots=4,
        limits=_limits((5, 30), (2, 5), (4, 14), 20),
    ),
}

_FLOORS_AND_CEILINGS = (
    "solution_min",
    "solution_max",
    "depth_min",
    "depth_max",
    "actions_min",
    "actions_max",
)


def check_presets(
    presets: Mapping[str, PresetDef], order: tuple[str, ...] = PRESET_ORDER
) -> list[str]:
    """Problems with a preset table: size overlaps, or limits that are not monotone."""
    problems: list[str] = []
    names = [n for n in order if n in presets]
    for prev_name, next_name in zip(names, names[1:], strict=False):
        prev, nxt = presets[prev_name], presets[next_name]
        for size in ("suspects", "methods", "locations"):
            if getattr(prev, size).max >= getattr(nxt, size).min:
                problems.append(f"{prev_name}/{next_name}: {size} ranges overlap")
        for field in _FLOORS_AND_CEILINGS:
            if getattr(prev.limits, field) > getattr(nxt.limits, field):
                problems.append(f"{prev_name}/{next_name}: {field} is not monotone")
        if prev.limits.decisive_pct_max < nxt.limits.decisive_pct_max:
            problems.append(f"{prev_name}/{next_name}: decisive_pct_max is not monotone")
    return problems


def derive_spec(name: str, pack: Pack, presets: Mapping[str, PresetDef] = PRESETS) -> Spec:
    """The effective spec for a preset on a pack: sizes are min(preset max, pack capacity)."""
    preset = presets.get(name)
    if preset is None:
        raise UnsupportedPreset(f"unknown preset {name!r}")
    caps = pack.capacity
    sizes = {
        "suspects": min(preset.suspects.max, caps.max_suspects),
        "methods": min(preset.methods.max, caps.max_methods),
        "locations": min(preset.locations.max, caps.max_locations),
        "record_kinds": min(preset.record_kinds.max, caps.max_record_kinds),
    }
    problems = [
        f"{size}={value} (needs at least {getattr(preset, size).min})"
        for size, value in sizes.items()
        if value < getattr(preset, size).min
    ]
    if pack.slots < preset.slots:
        problems.append(f"slots={pack.slots} (needs at least {preset.slots})")
    if problems:
        raise UnsupportedPreset(
            f"preset {name!r} unsupported by pack {pack.id!r}: " + ", ".join(problems)
        )
    return Spec(
        preset=name,
        suspects=sizes["suspects"],
        methods=sizes["methods"],
        motives=sizes["suspects"],
        locations=sizes["locations"],
        record_kinds=sizes["record_kinds"],
        slots=pack.slots,
        limits=preset.limits,
    )


def supported_presets(pack: Pack, presets: Mapping[str, PresetDef] = PRESETS) -> tuple[str, ...]:
    supported: list[str] = []
    for name in presets:
        try:
            derive_spec(name, pack, presets)
        except UnsupportedPreset:
            continue
        supported.append(name)
    return tuple(supported)
