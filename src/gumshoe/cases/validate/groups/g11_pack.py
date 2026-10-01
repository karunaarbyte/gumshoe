"""Group 11: the only rules that need a Pack."""

from gumshoe.cases.model.enums import Origin, SourceKind
from gumshoe.cases.model.spec import UnsupportedPreset, derive_spec
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.report import Issue, Profile


def run(ctx: Ctx) -> list[Issue]:
    case, pack, ix = ctx.case, ctx.pack, ctx.index
    if ctx.profile is Profile.CUSTOM:
        return []
    out: list[Issue] = []
    if pack is None:
        if case.origin is Origin.GENERATED:
            skipped = ",".join(
                sorted(code for code, spec in CATALOGUE.items() if spec.requires_pack)
            )
            out.append(ctx.issue("PACK_RULES_SKIPPED", "pack", skipped=skipped))
        return out

    if case.origin is Origin.GENERATED:
        ref = case.pack_ref
        if ref is None or ref.id != pack.id or ref.skeleton_hash != pack.skeleton_hash():
            out.append(ctx.issue("PACK_MISMATCH", pack.id))
        try:
            derived = derive_spec(case.spec.preset, pack, ctx.presets)
        except UnsupportedPreset as exc:
            out.append(ctx.issue("SPEC_MISMATCH", "spec", reason=str(exc)))
        else:
            if derived != case.spec:
                out.append(
                    ctx.issue("SPEC_MISMATCH", "spec", reason="spec differs from the derived spec")
                )

    caps = pack.capacity
    counts = (
        ("suspects", len(case.suspects), caps.max_suspects),
        ("locations", len(case.locations), caps.max_locations),
        ("methods", len(case.methods), caps.max_methods),
        ("record_kinds", len({r.kind for r in case.record_sources}), caps.max_record_kinds),
    )
    for name, actual, maximum in counts:
        if actual > maximum:
            out.append(ctx.issue("PACK_CAPACITY", name, actual=actual, max=maximum))

    sources = {
        SourceKind.SEARCH: len(case.locations),
        SourceKind.INTERROGATE: len(case.suspects),
        SourceKind.RECORD: len(case.record_sources),
    }
    for kind in SourceKind:
        demand = sum(1 for f in case.facts if f.source.kind is kind)
        if (
            demand * 5 > 4 * case.spec.source_cap * sources[kind]
        ):  # demand > 0.8 x cap x sources, in integers
            out.append(
                ctx.issue(
                    "PACK_SOURCE_KIND_CAPACITY", kind.value, demand=demand, sources=sources[kind]
                )
            )

    scene = next((s for s in pack.scene_types if s.key == case.scene_type), None)
    if scene is None:
        out.append(ctx.issue("SCENE_NOT_IN_PACK", case.scene_type))
    else:
        for method in case.methods:
            if method.type not in scene.allowed_methods:
                out.append(ctx.issue("SCENE_METHOD_NOT_ALLOWED", method.id, scene=scene.key))

    roles = {r.key: r for r in pack.roles}
    for s in case.suspects:
        role = roles.get(s.role)
        if role is None:
            out.append(ctx.issue("ROLE_UNKNOWN", s.id, role=s.role))
            continue
        motive = ix.motives.get(s.motive)
        if motive is not None and motive.type not in role.motive_types:
            out.append(ctx.issue("ROLE_MOTIVE_NOT_ALLOWED", s.id, motive=motive.id))
        secret = ix.facts.get(s.secret_fact)
        if (
            secret is not None
            and secret.source.kind is SourceKind.RECORD
            and secret.source.target not in role.record_kinds
        ):
            out.append(
                ctx.issue("ROLE_RECORD_KIND_NOT_ALLOWED", s.id, record_kind=secret.source.target)
            )
    return out
