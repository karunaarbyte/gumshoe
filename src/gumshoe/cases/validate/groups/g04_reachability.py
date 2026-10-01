"""Group 4: can the player actually get everything the case contains?"""

from collections import Counter

from gumshoe.cases.model.entities import SourceRef
from gumshoe.cases.model.enums import Axis, SourceKind
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue


def _label(source: SourceRef) -> str:
    return f"{source.kind.value}:{source.target}" + (f"/{source.subject}" if source.subject else "")


def run(ctx: Ctx) -> list[Issue]:
    case, ix, graph, reach = ctx.case, ctx.index, ctx.graph, ctx.reach
    out: list[Issue] = []

    out += [ctx.issue("ORPHAN_FACT", f.id) for f in case.facts if f.id not in reach.facts]
    out += [ctx.issue("ORPHAN_ENTITY", s.id) for s in case.suspects if s.id not in reach.suspects]
    out += [
        ctx.issue("ORPHAN_ENTITY", loc.id)
        for loc in case.locations
        if not loc.decorative and loc.id not in reach.locations
    ]
    out += [
        ctx.issue("ORPHAN_ENTITY", f"{kind}/{subject}")
        for (kind, subject) in sorted(ix.record_sources)
        if (kind, subject) not in reach.record_sources
    ]

    per_source = Counter(f.source for f in case.facts)
    for source, count in sorted(per_source.items(), key=lambda item: _label(item[0])):
        if count > case.spec.source_cap:
            out.append(
                ctx.issue(
                    "SOURCE_CAP_EXCEEDED", _label(source), count=count, cap=case.spec.source_cap
                )
            )

    for axis in Axis:
        for cand in ix.candidates[axis]:
            touched = any(
                f.id in reach.facts
                and any(e.axis is axis and e.candidate == cand for e in f.effects)
                for f in case.facts
            )
            if not touched:
                out.append(ctx.issue("UNTOUCHABLE_CANDIDATE", cand, axis=axis))

    for s in case.suspects:
        speaks = any(
            f.id in reach.facts
            and (
                f.speaker == s.id
                or (f.source.kind is SourceKind.INTERROGATE and f.source.target == s.id)
            )
            for f in case.facts
        )
        if not speaks:
            out.append(ctx.issue("NO_STATEMENT", s.id))

    searched = {f.source.target for f in case.facts if f.source.kind is SourceKind.SEARCH}
    out += [
        ctx.issue("EMPTY_LOCATION", loc.id)
        for loc in case.locations
        if not loc.decorative and loc.id not in searched
    ]

    lies_by_speaker: dict[str, set[str]] = {}
    for f in case.facts:
        if not f.truthful and f.speaker is not None:
            lies_by_speaker.setdefault(f.speaker, set()).add(f.id)
    for f in case.facts:
        if (
            f.source.kind is SourceKind.RECORD
            and f.source.subject in lies_by_speaker
            and f.id in graph.anc
        ):
            own = sorted(lies_by_speaker[f.source.subject] & graph.anc[f.id])
            if own:
                out.append(ctx.issue("GATE_ON_OWN_LIE", f.id, *own))
    return out
