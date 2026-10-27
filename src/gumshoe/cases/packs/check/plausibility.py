"""Stage 5: plausibility (spec 4.3): roles, motives, scene types and methods that can be played."""

from collections import Counter

from gumshoe.cases.model.pack import MethodDef, Pack, SceneType
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.issues import PackIssue

MIN_ROLE_MOTIVES = 3
MIN_METHOD_SCENES = 2


def _placeable(method: MethodDef, scene: SceneType) -> bool:
    """Whether some trace of the method fits the scene's trace kinds and crime locations."""
    return any(
        t.kind in scene.allowed_trace_kinds and set(t.location_kinds) & set(scene.location_kinds)
        for t in method.traces
    )


def check(pack: Pack) -> list[PackIssue]:
    out: list[PackIssue] = []
    about_suspect = {d.key for d in pack.record_defs if d.subject == "suspect"}
    allowed = {m for role in pack.roles for m in role.motive_types}
    for role in pack.roles:
        base = f"roles.{role.key}"
        if not role.noun.strip():
            out.append(make("ROLE_NO_NOUN", f"{base}.noun"))
        if not role.record_kinds:
            out.append(make("ROLE_NO_RECORD_KIND", f"{base}.record_kinds"))
        elif not about_suspect.intersection(role.record_kinds):
            out.append(make("ROLE_NO_SUSPECT_RECORD", f"{base}.record_kinds"))
        distinct = len(set(role.motive_types))
        if distinct < MIN_ROLE_MOTIVES:
            out.append(
                make(
                    "ROLE_TOO_FEW_MOTIVES",
                    f"{base}.motive_types",
                    count=distinct,
                    needed=MIN_ROLE_MOTIVES,
                )
            )
    for record_def in pack.record_defs:
        base = f"record_defs.{record_def.key}"
        if not record_def.names:
            out.append(make("RECORD_NO_NAME", f"{base}.names"))
        if not record_def.location_kinds:
            out.append(make("RECORD_NO_LOCATION_KIND", f"{base}.location_kinds"))
        if record_def.subject == "event":
            out.append(make("RECORD_EVENT_SUBJECT", f"{base}.subject"))
    for motive in pack.motive_defs:
        if motive.key not in allowed:
            out.append(make("MOTIVE_UNREACHABLE", f"motive_defs.{motive.key}"))
    scenes_per_method = Counter(m for s in pack.scene_types for m in set(s.allowed_methods))
    for method in pack.method_defs:
        count = scenes_per_method[method.key]
        if count < MIN_METHOD_SCENES:
            out.append(
                make(
                    "METHOD_TOO_RARE",
                    f"method_defs.{method.key}",
                    count=count,
                    needed=MIN_METHOD_SCENES,
                )
            )
    methods = {m.key: m for m in pack.method_defs}
    for scene in pack.scene_types:
        base = f"scene_types.{scene.key}"
        if not scene.location_kinds:
            out.append(make("SCENE_NO_CRIME_LOCATION", f"{base}.location_kinds"))
            continue
        if len(set(scene.location_kinds)) > 1:
            out.append(
                make(
                    "SCENE_MANY_CRIME_LOCATIONS",
                    f"{base}.location_kinds",
                    count=len(set(scene.location_kinds)),
                )
            )
        for key in scene.allowed_methods:
            found = methods.get(key)
            if found is not None and not _placeable(found, scene):
                out.append(
                    make(
                        "SCENE_METHOD_IMPOSSIBLE",
                        f"{base}.allowed_methods[{key}]",
                        method=key,
                        scene=scene.key,
                    )
                )
    if len(pack.slot_defs) < pack.slots:
        out.append(
            make("SLOT_DEFS_TOO_FEW", "slot_defs", defs=len(pack.slot_defs), slots=pack.slots)
        )
    return out
