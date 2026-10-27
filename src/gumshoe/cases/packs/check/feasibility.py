"""Stage 6: whether each claimed preset can be built from the pack. The helpers here are the
roster rules the generator also uses."""

from collections.abc import Iterator, Mapping

from gumshoe.cases.model.pack import MethodDef, Pack, SceneType
from gumshoe.cases.model.spec import PresetDef
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.capacity import hosted_specs
from gumshoe.cases.packs.check.depths import feasible_depths
from gumshoe.cases.packs.issues import PackIssue


def holder_assignments(kinds: list[str], options: list[list[str]]) -> Iterator[dict[int, str]]:
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


def trace_ok(method: MethodDef, scene: SceneType, places: set[str]) -> bool:
    """Some trace of the method fits the scene's trace kinds and a non-scene chosen place."""
    return any(
        t.kind in scene.allowed_trace_kinds and places & set(t.location_kinds)
        for t in method.traces
    )


def reachable_location_records(pack: Pack, record_kinds: int) -> range:
    """How many of a case's record kinds can be location-subject, given the pack's kinds."""
    suspect = sum(1 for d in pack.record_defs if d.subject == "suspect")
    place = sum(1 for d in pack.record_defs if d.subject == "location")
    return range(max(0, record_kinds - suspect), min(record_kinds, place) + 1)


def no_depth_presets(pack: Pack, presets: Mapping[str, PresetDef]) -> set[str]:
    out: set[str] = set()
    for name, spec in hosted_specs(pack, presets):
        counts = reachable_location_records(pack, spec.record_kinds)
        if not any(feasible_depths(spec, n) for n in counts):
            out.add(name)
    return out


def check(pack: Pack, presets: Mapping[str, PresetDef]) -> list[PackIssue]:
    return [
        make("PRESET_NO_DEPTH", f"meta.presets[{name}]", preset=name)
        for name in sorted(no_depth_presets(pack, presets))
    ]
