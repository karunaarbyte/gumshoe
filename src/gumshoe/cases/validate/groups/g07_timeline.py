"""Group 7: the timeline and every claim made about it."""

from gumshoe.cases.model.enums import Axis, ClaimKind, EffectKind, FactKind
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue

CRIME = "crime"


def run(ctx: Ctx) -> list[Issue]:
    case, ix = ctx.case, ctx.index
    out: list[Issue] = []

    where: dict[tuple[str, int], set[str]] = {}
    for e in case.timeline:
        where.setdefault((e.actor, e.slot), set()).add(e.place)
    for (actor, slot), places in sorted(where.items()):
        if len(places) > 1:
            out.append(
                ctx.issue("DOUBLE_BOOKED", actor, slot=slot, places=",".join(sorted(places)))
            )

    crimes = [e for e in case.timeline if e.action == CRIME]
    if not crimes:
        out.append(ctx.issue("NO_CRIME_EVENT", "timeline"))
    elif len(crimes) > 1:
        out.append(ctx.issue("MULTIPLE_CRIME_EVENTS", *(e.id for e in crimes)))

    for f in case.facts:
        claim = f.claim
        if claim is None or claim.kind is not ClaimKind.PRESENCE:
            continue
        actual = where.get((claim.actor, claim.slot), set())
        if f.truthful:
            if actual and claim.place not in actual:
                out.append(ctx.issue("CLAIM_CONTRADICTS_TIMELINE", f.id))
        elif not actual or claim.place in actual:
            out.append(ctx.issue("LIE_CONSISTENT_WITH_TIMELINE", f.id))

    if crimes:
        crime = crimes[0]
        at_scene = {
            e.actor for e in case.timeline if e.slot == crime.slot and e.place == crime.place
        }
        culprit = case.truth.who
        if culprit not in at_scene or (len(crimes) == 1 and crime.actor != culprit):
            out.append(ctx.issue("CULPRIT_NO_OPPORTUNITY", culprit, axis=Axis.WHO))
        for suspect in sorted(at_scene):
            if suspect == culprit or suspect not in ix.suspects:
                continue
            ruled = any(
                f.truthful
                and any(
                    eff.axis is Axis.WHO
                    and eff.candidate == suspect
                    and eff.kind is EffectKind.RULES_OUT
                    for eff in f.effects
                )
                for f in case.facts
            )
            if not ruled:
                out.append(ctx.issue("OPPORTUNITY_NOT_RULED_OUT", suspect, axis=Axis.WHO))
        for f in case.facts:
            if f.kind is not FactKind.ALIBI or not f.truthful:
                continue
            for eff in f.effects:
                if eff.axis is Axis.WHO and eff.kind is EffectKind.RULES_OUT:
                    c = f.claim
                    if (
                        c is None
                        or c.kind is not ClaimKind.PRESENCE
                        or c.actor != eff.candidate
                        or c.slot != crime.slot
                        or c.place == crime.place
                    ):
                        out.append(ctx.issue("ALIBI_NOT_ELSEWHERE", f.id, eff.candidate))
    return out
