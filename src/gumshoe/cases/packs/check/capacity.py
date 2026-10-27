"""Stage 6: capacity vs demand at every claimed preset, and monotone effective sizes."""

from collections.abc import Mapping
from math import comb, perm

from gumshoe.cases.model.entities import Spec
from gumshoe.cases.model.pack import Pack, RecordDef, SceneType
from gumshoe.cases.model.spec import PRESET_ORDER, PresetDef, UnsupportedPreset, derive_spec
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.issues import PackIssue

MIN_LOCATION_KINDS = 3
MIN_HOSTING_SCENES = 3  # scene types able to carry a preset's method count, else it is one place
SIZES = ("suspects", "methods", "locations", "record_kinds", "slots")
# Stage 7 enumerates every matching of every roster; a preset whose upper bound on that work is
# above this is unsupported here (and so never enumerated), which keeps the load bounded and
# stage 7 exact for every preset it does check.
MATCHING_BUDGET = 5_000_000


def matching_bound(pack: Pack, suspects: int) -> int:
    """An upper bound on stage 7's work for one suspect count: rosters x motive assignments."""
    if suspects <= 0:
        return 1  # one empty roster, one empty assignment
    return comb(len(pack.roles), suspects) * perm(len(pack.motive_defs), suspects)


def _order(name: str) -> int:
    return PRESET_ORDER.index(name) if name in PRESET_ORDER else len(PRESET_ORDER)


def usable_kind(record: RecordDef, scene: SceneType) -> bool:
    """Subject suspect, lists one of the scene's location kinds and at least one other kind."""
    if record.subject != "suspect":
        return False
    listed = set(record.location_kinds)
    return any(kind in listed and listed - {kind} for kind in scene.location_kinds)


def eligible_roles(pack: Pack, scene: SceneType) -> list[str]:
    """The role keys that have a usable record kind for the scene, in sorted order."""
    records = {d.key: d for d in pack.record_defs}
    return sorted(
        role.key
        for role in pack.roles
        if any(k in records and usable_kind(records[k], scene) for k in role.record_kinds)
    )


def hosting_scenes(pack: Pack, spec: Spec) -> list[SceneType]:
    """The scene types that can carry the preset: enough methods and enough eligible roles."""
    return [
        s
        for s in pack.scene_types
        if len(set(s.allowed_methods)) >= spec.methods
        and len(eligible_roles(pack, s)) >= spec.suspects
    ]


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
    bound = matching_bound(pack, spec.suspects)
    if bound > MATCHING_BUDGET:
        problems.append(
            f"matching check too large (roles={len(pack.roles)},"
            f" motive types={len(pack.motive_defs)}, up to {bound} matchings;"
            f" the limit is {MATCHING_BUDGET})"
        )
    hosting = len(hosting_scenes(pack, spec))
    if hosting < MIN_HOSTING_SCENES:
        problems.append(f"hosting scenes={hosting} (needs at least {MIN_HOSTING_SCENES})")
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


def pool_problems(pack: Pack) -> list[PackIssue]:
    """Capacity above the pool it draws from can never be used up; fewer than three location
    kinds leaves a case with a crime scene and nowhere to search."""
    out: list[PackIssue] = []
    cap = pack.capacity
    chosen_kinds = sum(1 for d in pack.record_defs if d.subject in ("suspect", "location"))
    pools = (
        ("max_suspects", "suspects", cap.max_suspects, len(pack.roles)),
        ("max_locations", "locations", cap.max_locations, len(pack.location_defs)),
        ("max_methods", "methods", cap.max_methods, len(pack.method_defs)),
        ("max_record_kinds", "record kinds", cap.max_record_kinds, chosen_kinds),
    )
    for key, what, capacity, pool in pools:
        if capacity > pool:
            out.append(
                make(
                    "CAPACITY_EXCEEDS_POOL",
                    f"capacity.{key}",
                    what=what,
                    capacity=capacity,
                    pool=pool,
                )
            )
    if len(pack.location_defs) < MIN_LOCATION_KINDS:
        out.append(
            make(
                "LOCATION_KINDS_TOO_FEW",
                "location_defs",
                count=len(pack.location_defs),
                needed=MIN_LOCATION_KINDS,
            )
        )
    return out
