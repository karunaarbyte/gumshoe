"""The roster stage: scene, roles and names, record kinds, methods, motives and locations.

Pool samples use rendezvous `rank` (never file order). Choices among combinations enumerate
the feasible ones and `choice` one by index, so there is no re-draw loop and no cap.
"""

from collections.abc import Iterator
from itertools import combinations

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import (
    RosterLocation,
    RosterMethod,
    RosterMotive,
    RosterOut,
    RosterSuspect,
)
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.model.pack import MethodDef, Pack, RecordDef, RoleDef, SceneType
from gumshoe.cases.packs.check.capacity import eligible_roles, hosting_scenes, usable_kind
from gumshoe.cases.packs.check.matching import matchings


def _pick_name(role: RoleDef, used: set[str], stream: Stream) -> str:
    """The role's best-ranked name that no earlier suspect has."""
    for name in stream.rank([e.text for e in role.names], f"name/{role.key}"):
        if name not in used:
            return name
    raise GenerationError(f"role {role.key!r} has no unused name")


def _usable_kinds(role: RoleDef, scene: SceneType, records: dict[str, RecordDef]) -> list[str]:
    return [k for k in role.record_kinds if k in records and usable_kind(records[k], scene)]


def _holder_assignments(kinds: list[str], options: list[list[str]]) -> Iterator[dict[int, str]]:
    """Every way to give each kind its own holder: a distinct role index whose options list it."""
    held: dict[int, str] = {}

    def go() -> Iterator[dict[int, str]]:
        if len(held) == len(kinds):
            yield dict(held)
            return
        kind = kinds[len(held)]  # one kind is placed per level, so the level is len(held)
        for role, opts in enumerate(options):
            if role not in held and kind in opts:
                held[role] = kind
                yield from go()
                del held[role]

    yield from go()


def _record_kinds_and_secrets(
    pack: Pack, scene: SceneType, roles: list[RoleDef], size: int, stream: Stream
) -> tuple[tuple[str, ...], list[str]]:
    """Choose the K record kinds and every suspect's secret record kind together. Every chosen
    role gets a usable kind, and every chosen suspect-subject kind is the secret kind of some
    suspect, so nobody needs a second record (a second record would single them out)."""
    records = {d.key: d for d in pack.record_defs}
    usable = [sorted(_usable_kinds(r, scene, records)) for r in roles]
    feasible: list[tuple[tuple[str, ...], dict[int, str]]] = []
    for subset in combinations(sorted(records), size):
        if any(not set(opts) & set(subset) for opts in usable):
            continue
        held_kinds = [k for k in subset if records[k].subject == "suspect"]
        feasible += [(subset, h) for h in _holder_assignments(held_kinds, usable)]
    if not feasible:
        raise GenerationError("no record-kind set gives every role a kind and every kind a holder")
    subset, holders = stream.choice(feasible)
    secrets = [
        holders[i]
        if i in holders
        else stream.child(f"record_kind/{role.key}").choice(sorted(set(usable[i]) & set(subset)))
        for i, role in enumerate(roles)
    ]
    return subset, secrets


def _trace_ok(method: MethodDef, scene: SceneType, places: set[str]) -> bool:
    """Some trace of the method fits the scene's trace kinds and a non-scene chosen place."""
    return any(
        t.kind in scene.allowed_trace_kinds and places & set(t.location_kinds)
        for t in method.traces
    )


def location_kinds(
    pack: Pack,
    scene: SceneType,
    secret_kinds: list[str],
    methods: list[MethodDef],
    record_kinds: tuple[str, ...],
    size: int,
    stream: Stream,
) -> tuple[str, ...]:
    """The non-scene location kinds to use: (c) every method has a non-scene place for a trace,
    (b') every suspect's record kind attests a non-scene place, (g') every location-subject
    record kind attests a chosen place."""
    scene_kind = scene.location_kinds[0]
    records = {d.key: d for d in pack.record_defs}
    others = sorted({d.key for d in pack.location_defs} - {scene_kind})
    feasible = []
    for subset in combinations(others, size - 1):
        chosen = set(subset)
        if not all(_trace_ok(m, scene, chosen) for m in methods):
            continue
        if not all(chosen & set(records[kind].location_kinds) for kind in secret_kinds):
            continue
        place_subject = [
            records[k] for k in record_kinds if k in records and records[k].subject == "location"
        ]
        if not all((chosen | {scene_kind}) & set(r.location_kinds) for r in place_subject):
            continue
        feasible.append(subset)
    if not feasible:
        raise GenerationError("no set of locations satisfies the trace and record constraints")
    return stream.choice(feasible)


def run(ctx: GenContext, stream: Stream) -> RosterOut:
    pack, spec = ctx.pack, ctx.spec
    hosting = hosting_scenes(pack, spec)
    if not hosting:
        raise GenerationError("the pack has no scene that can host the preset")
    scene_key = stream.rank([s.key for s in hosting], "scene")[0]
    scene = next(s for s in hosting if s.key == scene_key)
    if len(scene.location_kinds) != 1:
        raise GenerationError(f"scene {scene.key!r} must have exactly one location kind")
    roles_by_key = {r.key: r for r in pack.roles}

    eligible = eligible_roles(pack, scene)
    role_keys = stream.rank(eligible, "roles")[: spec.suspects]
    roles = [roles_by_key[k] for k in role_keys]
    used: set[str] = set()
    names: list[str] = []
    for role in roles:
        names.append(_pick_name(role, used, stream))
        used.add(names[-1])

    kinds, secret_kinds = _record_kinds_and_secrets(pack, scene, roles, spec.record_kinds, stream)

    method_keys = stream.rank(sorted(set(scene.allowed_methods)), "methods")[: spec.methods]
    methods_by_key = {m.key: m for m in pack.method_defs}
    methods = [methods_by_key[k] for k in method_keys]

    allowed = {r.key: tuple(sorted(set(r.motive_types))) for r in roles}
    ordered = tuple(sorted(allowed))
    assignments = list(matchings(allowed, ordered))
    if not assignments:
        raise GenerationError("the chosen roles have no perfect matching to motives")
    motive_of = dict(zip(ordered, stream.choice(assignments), strict=True))
    motive_defs = {m.key: m for m in pack.motive_defs}

    places = location_kinds(
        pack,
        scene,
        secret_kinds,
        methods,
        kinds,
        spec.locations,
        stream,
    )

    suspects = tuple(
        RosterSuspect(
            pos=f"s{i}",
            name=name,
            role=role.key,
            noun=role.noun,
            label=f"{name} the {role.noun}",
            aliases=(name, f"the {role.noun}"),
            motive_pos=f"v{i}",
            record_kind=kind,
        )
        for i, (role, name, kind) in enumerate(zip(roles, names, secret_kinds, strict=True))
    )
    return RosterOut(
        scene_type=scene.key,
        suspects=suspects,
        methods=tuple(
            RosterMethod(pos=f"m{i}", key=m.key, label=m.label, aliases=m.aliases)
            for i, m in enumerate(methods)
        ),
        motives=tuple(
            RosterMotive(
                pos=f"v{i}",
                key=motive_of[role.key],
                label=motive_defs[motive_of[role.key]].label,
                aliases=motive_defs[motive_of[role.key]].aliases,
            )
            for i, role in enumerate(roles)
        ),
        locations=tuple(
            RosterLocation(pos=f"l{i}", kind=kind)
            for i, kind in enumerate((scene.location_kinds[0], *places))
        ),
        record_kinds=kinds,
    )
