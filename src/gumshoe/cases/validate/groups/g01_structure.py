"""Group 1: structure and size caps. Runs on arbitrary input: size first, never raises."""

from collections import Counter

from gumshoe.cases.core.ids import is_valid_id
from gumshoe.cases.model.entities import Method, Motive, SourceRef, Suspect
from gumshoe.cases.model.enums import Axis, EffectKind, RecordSubjectType, SourceKind
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue

MAX_FACTS = 200
MAX_PER_KIND = 64
MAX_LIST = 16  # aliases, effects, requires, exposed_by, timeline_ref, knows (per entity)
MAX_TEXT = 200  # characters in a label or alias


def run(ctx: Ctx) -> list[Issue]:
    case = ctx.case
    sizes = (
        case.suspects,
        case.locations,
        case.methods,
        case.motives,
        case.record_sources,
        case.timeline,
    )
    if (
        len(case.facts) > MAX_FACTS
        or any(len(group) > MAX_PER_KIND for group in sizes)
        or _oversized_entity(ctx)
    ):
        return [ctx.issue("TOO_LARGE", "case", facts=len(case.facts))]
    out: list[Issue] = []
    out += _ids(ctx)
    out += _counts_and_truth(ctx)
    out += _references(ctx)
    out += _fact_shapes(ctx)
    out += _slots(ctx)
    return out


def _oversized_entity(ctx: Ctx) -> bool:
    """A single entity with an enormous list or label could make later groups slow."""
    case = ctx.case
    lists: list[tuple[object, ...]] = []
    lists += [(f.requires, f.effects, f.exposed_by, f.timeline_ref) for f in case.facts]
    lists += [(s.aliases, s.requires, s.knows) for s in case.suspects]
    lists += [(loc.aliases, loc.requires) for loc in case.locations]
    labelled: list[Suspect | Method | Motive] = [*case.suspects, *case.methods, *case.motives]
    lists += [(m.aliases,) for m in case.methods]
    lists += [(m.aliases,) for m in case.motives]
    lists += [(r.requires,) for r in case.record_sources]
    if any(len(items) > MAX_LIST for group in lists for items in group):  # type: ignore[arg-type]
        return True
    texts = [x.label for x in labelled] + [a for x in labelled for a in x.aliases]
    return any(len(text) > MAX_TEXT for text in texts)


def _ids(ctx: Ctx) -> list[Issue]:
    case = ctx.case
    entity_ids = [
        e.id
        for group in (
            case.suspects,
            case.locations,
            case.methods,
            case.motives,
            case.timeline,
            case.facts,
        )
        for e in group
    ]
    keyed = entity_ids + [f"{r.kind}/{r.subject}" for r in case.record_sources]
    out = [ctx.issue("DUPLICATE_ID", i) for i, n in sorted(Counter(keyed).items()) if n > 1]
    out += [ctx.issue("BAD_ID", i) for i in sorted(set(entity_ids)) if not is_valid_id(i)]
    return out


def _counts_and_truth(ctx: Ctx) -> list[Issue]:
    case, ix, spec = ctx.case, ctx.index, ctx.case.spec
    out: list[Issue] = []
    pairs = (
        ("suspects", len(case.suspects), spec.suspects),
        ("methods", len(case.methods), spec.methods),
        ("motives", len(case.motives), spec.motives),
        ("locations", len(case.locations), spec.locations),
        ("record_kinds", len({r.kind for r in case.record_sources}), spec.record_kinds),
    )
    for name, actual, expected in pairs:
        if actual != expected:
            out.append(ctx.issue("COUNT_MISMATCH", name, expected=expected, actual=actual))
    for axis in Axis:
        if ix.truth(axis) not in ix.candidates[axis]:
            out.append(ctx.issue("TRUTH_NOT_CANDIDATE", ix.truth(axis), axis=axis))
    return out


def _references(ctx: Ctx) -> list[Issue]:
    case, ix = ctx.case, ctx.index
    out: list[Issue] = []
    facts, suspects, locations, events = (
        set(ix.facts),
        set(ix.suspects),
        set(ix.locations),
        set(ix.events),
    )

    def need(owner: str, field: str, ref: str, valid: set[str]) -> None:
        if ref not in valid:
            out.append(ctx.issue("DANGLING_REF", owner, ref, field=field))

    def source(owner: str, field: str, ref: SourceRef) -> None:
        if (ref.kind is SourceKind.RECORD) != bool(ref.subject):
            out.append(ctx.issue("SOURCE_SHAPE", owner, field=field))
            return
        if ref.kind is SourceKind.SEARCH:
            need(owner, field, ref.target, locations)
        elif ref.kind is SourceKind.INTERROGATE:
            need(owner, field, ref.target, suspects)
        elif (ref.target, ref.subject or "") not in ix.record_sources:
            out.append(
                ctx.issue(
                    "UNDECLARED_RECORD_SOURCE", owner, f"{ref.target}/{ref.subject}", field=field
                )
            )

    for ref in case.start.locations:
        need("start", "locations", ref, locations)
    for ref in case.start.suspects:
        need("start", "suspects", ref, suspects)
    for ref in case.start.facts:
        need("start", "facts", ref, facts)
    for s in case.suspects:
        for ref in s.requires:
            need(s.id, "requires", ref, facts)
        for ref in s.knows:
            need(s.id, "knows", ref, facts)
        if s.secret_fact:
            need(s.id, "secret_fact", s.secret_fact, facts)
        need(s.id, "motive", s.motive, set(ix.motives))
    for loc in case.locations:
        for ref in loc.requires:
            need(loc.id, "requires", ref, facts)
    for rs in case.record_sources:
        owner = f"{rs.kind}/{rs.subject}"
        for ref in rs.requires:
            need(owner, "requires", ref, facts)
        valid = {
            RecordSubjectType.SUSPECT: suspects,
            RecordSubjectType.LOCATION: locations,
            RecordSubjectType.EVENT: events,
        }[rs.subject_type]
        need(owner, "subject", rs.subject, valid)
    for e in case.timeline:
        need(e.id, "actor", e.actor, suspects)
        need(e.id, "place", e.place, locations)
    for f in case.facts:
        for ref in f.requires:
            need(f.id, "requires", ref, facts)
        for ref in f.exposed_by:
            need(f.id, "exposed_by", ref, facts)
        for ref in f.timeline_ref:
            need(f.id, "timeline_ref", ref, events)
        if f.speaker is not None:
            need(f.id, "speaker", f.speaker, suspects)
        if f.claim is not None:
            need(f.id, "claim.actor", f.claim.actor, suspects)
            if f.claim.place is not None:
                need(f.id, "claim.place", f.claim.place, locations)
        source(f.id, "source", f.source)
        if f.exposure_hook is not None:
            source(f.id, "exposure_hook", f.exposure_hook)
    return out


def _fact_shapes(ctx: Ctx) -> list[Issue]:
    case, ix = ctx.case, ctx.index
    out: list[Issue] = []
    start = set(case.start.facts)
    for f in case.facts:
        proves_axes = {e.axis for e in f.effects if e.kind is EffectKind.PROVES}
        if len(proves_axes) > 1:
            out.append(ctx.issue("MULTI_AXIS_PROVES", f.id))
        if f.id in start and proves_axes:
            out.append(ctx.issue("START_PROVES", f.id))
        for e in f.effects:
            if e.candidate in ix.candidates[e.axis]:
                continue
            if any(e.candidate in ix.candidates[other] for other in Axis if other is not e.axis):
                out.append(ctx.issue("EFFECT_WRONG_AXIS", f.id, e.candidate, axis=e.axis))
            else:
                out.append(ctx.issue("DANGLING_REF", f.id, e.candidate, field="effects"))
    return out


def _slots(ctx: Ctx) -> list[Issue]:
    case = ctx.case
    out: list[Issue] = []
    slots = case.spec.slots
    if slots < 4:
        out.append(ctx.issue("SLOTS_TOO_FEW", "spec", slots=slots))
    for e in case.timeline:
        if not 0 <= e.slot < slots:
            out.append(ctx.issue("SLOT_OUT_OF_RANGE", e.id, slot=e.slot))
    for f in case.facts:
        if f.claim is not None and not 0 <= f.claim.slot < slots:
            out.append(ctx.issue("SLOT_OUT_OF_RANGE", f.id, slot=f.claim.slot))
    return out
