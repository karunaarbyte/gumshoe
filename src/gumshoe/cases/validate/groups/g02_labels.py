"""Group 2: can every candidate be told apart by label? Deterministic string logic only."""

from dataclasses import dataclass
from itertools import combinations

from gumshoe.cases.core.labels import distinctive, overlap_kind, token_set
from gumshoe.cases.core.text import normalise, tokens
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue

MAX_LENGTH_RATIO = 3


@dataclass(frozen=True)
class Cand:
    axis: Axis
    id: str
    label: str
    aliases: tuple[str, ...]


def _candidates(ctx: Ctx) -> list[Cand]:
    case = ctx.case
    return (
        [Cand(Axis.WHO, s.id, s.label, s.aliases) for s in case.suspects]
        + [Cand(Axis.HOW, m.id, m.label, m.aliases) for m in case.methods]
        + [Cand(Axis.WHY, m.id, m.label, m.aliases) for m in case.motives]
    )


def run(ctx: Ctx) -> list[Issue]:
    cands = _candidates(ctx)
    out: list[Issue] = []

    by_label: dict[str, list[str]] = {}
    for c in cands:
        norm = normalise(c.label)
        if norm:
            by_label.setdefault(norm, []).append(c.id)
    for norm, ids in sorted(by_label.items()):
        if len(ids) > 1:
            out.append(ctx.issue("LABEL_DUPLICATE", *sorted(ids), label=norm))

    for axis in Axis:
        same_axis = sorted((c for c in cands if c.axis is axis), key=lambda c: c.id)
        for a, b in combinations(same_axis, 2):
            kind = overlap_kind(a.label, b.label)
            if kind in ("subset", "substring"):
                out.append(ctx.issue("LABEL_OVERLAP", a.id, b.id, axis=axis, kind=kind))
        lengths = [max(len(tokens(c.label)), 1) for c in same_axis]
        if lengths and max(lengths) > MAX_LENGTH_RATIO * min(lengths):
            out.append(
                ctx.issue(
                    "LABEL_LENGTH_SKEW",
                    axis.value,
                    axis=axis,
                    longest=max(lengths),
                    shortest=min(lengths),
                )
            )

    owners: dict[str, set[str]] = {}  # normalised label or alias -> candidates that use it
    for c in cands:
        for text in (c.label, *c.aliases):
            norm = normalise(text)
            if norm:
                owners.setdefault(norm, set()).add(c.id)
    seen: set[frozenset[str]] = set()
    for c in cands:
        for alias in c.aliases:
            na = normalise(alias)
            for other_id in sorted(owners.get(na, set()) - {c.id}):
                pair = frozenset({c.id, other_id})
                if pair not in seen and na:
                    seen.add(pair)
                    out.append(ctx.issue("ALIAS_COLLISION", *sorted(pair), alias=na))

    suspect_tokens: frozenset[str] = frozenset().union(
        *(token_set(c.label, *c.aliases) for c in cands if c.axis is Axis.WHO)
    )
    for c in cands:
        if c.axis is Axis.WHO:
            continue
        shared = token_set(c.label, *c.aliases) & suspect_tokens
        if shared:
            out.append(
                ctx.issue(
                    "LABEL_NAME_COLLISION", c.id, axis=c.axis, tokens=",".join(sorted(shared))
                )
            )

    token_sets = {c.id: token_set(c.label, *c.aliases) for c in cands}
    for c in cands:
        others = [token_sets[o.id] for o in cands if o.axis is c.axis and o.id != c.id]
        if not normalise(c.label) or not distinctive(token_sets[c.id], others):
            out.append(ctx.issue("NO_DISTINCTIVE_TOKEN", c.id, axis=c.axis))
    return out
