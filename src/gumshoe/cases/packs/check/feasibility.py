"""Stage 6: whether each claimed preset can be built from the pack. The helpers here are the
roster rules the generator also uses."""

from collections.abc import Iterator

from gumshoe.cases.model.pack import MethodDef, SceneType


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
