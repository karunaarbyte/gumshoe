"""Stage 2: closed references. Every key a table names must be defined somewhere in the pack."""

from collections import Counter
from collections.abc import Iterable

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.issues import PackIssue
from gumshoe.cases.packs.suggest import did_you_mean


def _duplicates(path: str, keys: Iterable[str]) -> list[PackIssue]:
    return [
        make("DUPLICATE_KEY", f"{path}[{key}]", name=key)
        for key, count in sorted(Counter(keys).items())
        if count > 1
    ]


def check(pack: Pack) -> list[PackIssue]:
    known = {
        "UNKNOWN_LOCATION_KIND": {d.key for d in pack.location_defs},
        "UNKNOWN_RECORD_KIND": set(pack.known_record_kinds),
        "UNKNOWN_METHOD": {d.key for d in pack.method_defs},
        "UNKNOWN_MOTIVE_TYPE": {d.key for d in pack.motive_defs},
        "UNKNOWN_TRACE_KIND": {t.kind for m in pack.method_defs for t in m.traces},
    }
    out: list[PackIssue] = []

    def unknown(code: str, path: str, names: Iterable[str]) -> None:
        for name in names:
            if name not in known[code]:
                out.append(
                    make(code, f"{path}[{name}]", did_you_mean(name, known[code]), name=name)
                )

    for scene in pack.scene_types:
        base = f"scene_types.{scene.key}"
        unknown("UNKNOWN_LOCATION_KIND", f"{base}.location_kinds", scene.location_kinds)
        unknown("UNKNOWN_METHOD", f"{base}.allowed_methods", scene.allowed_methods)
        unknown("UNKNOWN_TRACE_KIND", f"{base}.allowed_trace_kinds", scene.allowed_trace_kinds)
    for method in pack.method_defs:
        for trace in method.traces:
            where = f"method_defs.{method.key}.traces[{trace.kind}].location_kinds"
            unknown("UNKNOWN_LOCATION_KIND", where, trace.location_kinds)
        out += _duplicates(f"method_defs.{method.key}.traces", (t.kind for t in method.traces))
    for role in pack.roles:
        unknown("UNKNOWN_RECORD_KIND", f"roles.{role.key}.record_kinds", role.record_kinds)
        unknown("UNKNOWN_MOTIVE_TYPE", f"roles.{role.key}.motive_types", role.motive_types)
    out += _duplicates("meta.presets", pack.presets)
    out += _duplicates("slot_defs", (s.key for s in pack.slot_defs))
    out += _duplicates("families", (f.id for f in pack.families))
    out += _duplicates("location_defs", (d.key for d in pack.location_defs))
    out += _duplicates("record_defs", (d.key for d in pack.record_defs))
    out += _duplicates("method_defs", (d.key for d in pack.method_defs))
    out += _duplicates("motive_defs", (d.key for d in pack.motive_defs))
    return out
