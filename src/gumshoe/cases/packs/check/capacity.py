"""Stage 6: capacity vs demand at every claimed preset, and monotone effective sizes."""

from collections.abc import Mapping

from gumshoe.cases.model.entities import Spec
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESET_ORDER, PresetDef, UnsupportedPreset, derive_spec
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.issues import PackIssue

MIN_HOSTING_SCENES = 3  # scene types able to carry a preset's method count, else it is one place
SIZES = ("suspects", "methods", "locations", "record_kinds", "slots")


def _order(name: str) -> int:
    return PRESET_ORDER.index(name) if name in PRESET_ORDER else len(PRESET_ORDER)


def _preset_problems(
    pack: Pack, name: str, presets: Mapping[str, PresetDef]
) -> tuple[Spec | None, str]:
    """The effective spec when the pack can host the preset, else (None, the reasons)."""
    try:
        spec = derive_spec(name, pack, presets)
    except UnsupportedPreset as exc:
        return None, str(exc)
    problems = []
    if spec.suspects > len(pack.roles):
        problems.append(f"roles={len(pack.roles)} (needs at least {spec.suspects})")
    if spec.suspects > len(pack.motive_defs):
        problems.append(f"motive types={len(pack.motive_defs)} (needs at least {spec.suspects})")
    hosting = sum(1 for s in pack.scene_types if len(set(s.allowed_methods)) >= spec.methods)
    if hosting < MIN_HOSTING_SCENES:
        problems.append(
            f"scene types allowing {spec.methods} methods={hosting}"
            f" (needs at least {MIN_HOSTING_SCENES})"
        )
    return (None, "; ".join(problems)) if problems else (spec, "")


def hosted_specs(pack: Pack, presets: Mapping[str, PresetDef]) -> list[tuple[str, Spec]]:
    """The claimed presets the pack can host, in preset order, with their effective specs."""
    found = [(n, _preset_problems(pack, n, presets)[0]) for n in pack.presets]
    return sorted(((n, s) for n, s in found if s is not None), key=lambda item: _order(item[0]))


def check(pack: Pack, presets: Mapping[str, PresetDef]) -> list[PackIssue]:
    out: list[PackIssue] = []
    for name in pack.presets:
        spec, reason = _preset_problems(pack, name, presets)
        if spec is None:
            out.append(make("PRESET_UNSUPPORTED", f"meta.presets[{name}]", reason=reason))
    hosted = hosted_specs(pack, presets)
    for (previous, before), (name, after) in zip(hosted, hosted[1:], strict=False):
        for size in SIZES:
            if getattr(after, size) < getattr(before, size):
                out.append(
                    make(
                        "PRESET_NOT_MONOTONE",
                        f"meta.presets[{name}]",
                        size=size,
                        previous=previous,
                        preset=name,
                    )
                )
    return out
