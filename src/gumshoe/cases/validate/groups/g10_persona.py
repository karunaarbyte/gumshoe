"""Group 10: persona and secret consistency."""

from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue


def run(ctx: Ctx) -> list[Issue]:
    case, ix = ctx.case, ctx.index
    out: list[Issue] = []
    for s in case.suspects:
        if not s.secret_fact:
            out.append(ctx.issue("SECRET_FACT_MISSING", s.id))
        else:
            secret = ix.facts.get(s.secret_fact)
            if secret is not None and not (
                secret.truthful
                and secret.source.kind is SourceKind.RECORD
                and secret.source.subject == s.id
            ):
                out.append(ctx.issue("SECRET_SOURCE_MISMATCH", s.id, secret.id))
        for fact_id in s.knows:
            fact = ix.facts.get(fact_id)
            if fact is not None and not (
                fact.speaker == s.id
                or (fact.source.kind is SourceKind.INTERROGATE and fact.source.target == s.id)
            ):
                out.append(ctx.issue("KNOWS_NOT_SPEAKABLE", s.id, fact_id))
    if sorted(s.motive for s in case.suspects) != sorted(m.id for m in case.motives):
        out.append(ctx.issue("MOTIVE_MAPPING", "suspects"))
    return out
