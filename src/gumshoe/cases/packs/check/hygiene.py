"""Stage 4: label hygiene and leak rules (spec 4.4). A candidate's distinctive label tokens
may appear only in its own entries, and a motive's secret never reuses its own label."""

import unicodedata
from collections import Counter
from collections.abc import Iterator
from fractions import Fraction

from gumshoe.cases.core.labels import distinctive, token_set
from gumshoe.cases.core.text import tokens
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.lint import SAMPLES, blank_placeholders, render, template_items
from gumshoe.cases.packs.issues import PackIssue

LENGTH_TOLERANCE = Fraction(1, 5)  # 20%


def candidate_tokens(pack: Pack) -> dict[str, frozenset[str]]:
    """id -> distinctive tokens; an id is `method:<key>` or `motive:<key>`."""
    groups = (
        {f"method:{m.key}": token_set(m.label, *m.aliases) for m in pack.method_defs},
        {f"motive:{m.key}": token_set(m.label, *m.aliases) for m in pack.motive_defs},
    )
    out: dict[str, frozenset[str]] = {}
    for group in groups:
        for cid, own in group.items():
            out[cid] = distinctive(own, [t for other, t in group.items() if other != cid])
    return out


def _texts(pack: Pack) -> Iterator[tuple[str, str, str | None]]:
    """(path, prose, owner): owner is the candidate id a text belongs to, if any. A template's
    placeholders are syntax, not prose, so each becomes a space; a plain pool text (names,
    traits, slot phrases) has no placeholders and is scanned as written, braces and all."""
    owners = {}
    for method in pack.method_defs:
        for trace in method.traces:
            for i in range(len(trace.templates)):
                path = f"method_defs.{method.key}.traces[{trace.kind}].templates[{i}]"
                owners[path] = f"method:{method.key}"
            for i in range(len(trace.absent)):
                path = f"method_defs.{method.key}.traces[{trace.kind}].absent[{i}]"
                owners[path] = f"method:{method.key}"
        for i in range(len(method.clues)):
            owners[f"method_defs.{method.key}.clues[{i}]"] = f"method:{method.key}"
    for motive in pack.motive_defs:
        for i in range(len(motive.secrets)):
            owners[f"motive_defs.{motive.key}.secrets[{i}]"] = f"motive:{motive.key}"
        for i in range(len(motive.hints)):
            owners[f"motive_defs.{motive.key}.hints[{i}]"] = f"motive:{motive.key}"
    for path, text in template_items(pack):
        yield path, blank_placeholders(text), owners.get(path)
    for location in pack.location_defs:
        for i, entry in enumerate(location.names):
            yield f"location_defs.{location.key}.names[{i}]", entry.text, None
    for i, entry in enumerate(pack.victims):
        yield f"victims[{i}]", entry.text, None
    for role in pack.roles:
        for i, entry in enumerate(role.names):
            yield f"roles.{role.key}.names[{i}]", entry.text, None
        for i, trait in enumerate(role.traits):
            yield f"roles.{role.key}.traits[{i}]", trait, None
        if role.style:
            yield f"roles.{role.key}.style", role.style, None
    for record_def in pack.record_defs:
        for i, entry in enumerate(record_def.names):
            yield f"record_defs.{record_def.key}.names[{i}]", entry.text, None
    for slot in pack.slot_defs:
        yield f"slot_defs[{slot.key}]", f"{slot.at} {slot.during}", None


def _leaks(pack: Pack) -> list[PackIssue]:
    candidates = candidate_tokens(pack)
    out: list[PackIssue] = []
    for path, text, owner in _texts(pack):
        words = set(tokens(text))
        for cid, owned in sorted(candidates.items()):
            hit = words & owned
            if not hit:
                continue
            token = sorted(hit)[0]
            if cid != owner:
                out.append(make("LABEL_TOKEN_LEAK", path, token=token, candidate=cid))
            elif cid.startswith("motive:"):
                out.append(make("SECRET_REUSES_LABEL", path, candidate=cid, token=token))
    return out


def _trace_skew(pack: Pack) -> list[PackIssue]:
    templates = {m.key: [t for tr in m.traces for t in tr.templates] for m in pack.method_defs}
    if len(templates) < 2:
        return []
    out: list[PackIssue] = []
    target = max(len(v) for v in templates.values())
    for key, items in sorted(templates.items()):
        if len(items) < target:
            out.append(
                make("TRACE_COUNT_SKEW", f"method_defs.{key}", count=len(items), target=target)
            )
    means = {
        key: Fraction(sum(len(render(t, SAMPLES[0])) for t in items), len(items))
        for key, items in templates.items()
        if items
    }
    if means:
        overall = sum(means.values(), Fraction(0)) / len(means)
        for key, mean in sorted(means.items()):
            if overall > 0 and abs(mean - overall) > overall * LENGTH_TOLERANCE:
                out.append(
                    make(
                        "TRACE_LENGTH_SKEW",
                        f"method_defs.{key}",
                        mean=f"{float(mean):.1f}",
                        overall=f"{float(overall):.1f}",
                    )
                )
    return out


def _role_collisions(pack: Pack) -> list[PackIssue]:
    """Role nouns and names may not share a token with each other (nouns) or with ANY method or
    motive label or alias token: the case validator's LABEL_NAME_COLLISION uses all tokens."""
    candidate_tokens: dict[str, str] = {}
    for kind, defs in (("method", pack.method_defs), ("motive", pack.motive_defs)):
        for d in defs:
            for token in sorted(token_set(d.label, *d.aliases)):
                candidate_tokens.setdefault(token, f"{kind}:{d.key}")
    out: list[PackIssue] = []
    noun_owner: dict[str, str] = {}
    for role in sorted(pack.roles, key=lambda r: r.key):
        base = f"roles.{role.key}"
        for token in sorted(token_set(role.noun)):
            owner = noun_owner.setdefault(token, role.key)
            if owner != role.key:
                out.append(
                    make(
                        "ROLE_TOKEN_COLLISION",
                        f"{base}.noun",
                        what="noun",
                        token=token,
                        other=f"role:{owner}",
                    )
                )
            if token in candidate_tokens:
                out.append(
                    make(
                        "ROLE_TOKEN_COLLISION",
                        f"{base}.noun",
                        what="noun",
                        token=token,
                        other=candidate_tokens[token],
                    )
                )
        for i, entry in enumerate(role.names):
            for token in sorted(token_set(entry.text)):
                if token in candidate_tokens:
                    out.append(
                        make(
                            "ROLE_TOKEN_COLLISION",
                            f"{base}.names[{i}]",
                            what="name",
                            token=token,
                            other=candidate_tokens[token],
                        )
                    )
    role_tokens: dict[str, str] = {}
    for role in sorted(pack.roles, key=lambda r: r.key):
        for token in sorted(token_set(role.noun, *(e.text for e in role.names))):
            role_tokens.setdefault(token, f"role:{role.key}")
    for i, entry in enumerate(pack.victims):
        for token in sorted(token_set(entry.text)):
            other = candidate_tokens.get(token) or role_tokens.get(token)
            if other:
                out.append(
                    make(
                        "ROLE_TOKEN_COLLISION",
                        f"victims[{i}]",
                        what="name",
                        token=token,
                        other=other,
                    )
                )
    return out


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def same_name(a: str, b: str) -> bool:
    return _fold(a) == _fold(b)


def name_problems(pack: Pack) -> list[PackIssue]:
    out: list[PackIssue] = []
    seen: dict[str, str] = {}

    def see(path: str, text: str) -> None:
        key = _fold(text)
        if key in seen:
            out.append(make("NAME_DUPLICATE", path, name=text, other=seen[key]))
        else:
            seen[key] = text

    for role in sorted(pack.roles, key=lambda r: r.key):
        if not role.names:
            out.append(make("ROLE_NO_NAME", f"roles.{role.key}.names"))
        for i, entry in enumerate(role.names):
            see(f"roles.{role.key}.names[{i}]", entry.text)
    for i, entry in enumerate(pack.victims):
        see(f"victims[{i}]", entry.text)
    return out


def duplicate_problems(pack: Pack) -> list[PackIssue]:
    out: list[PackIssue] = []

    def scan(path: str, values: tuple[str, ...]) -> None:
        for value, n in sorted(Counter(values).items()):
            if n > 1:
                out.append(make("DUPLICATE_ENTRY", path, value=value))

    for scene in pack.scene_types:
        base = f"scene_types.{scene.key}"
        scan(f"{base}.location_kinds", scene.location_kinds)
        scan(f"{base}.allowed_methods", scene.allowed_methods)
        scan(f"{base}.allowed_trace_kinds", scene.allowed_trace_kinds)
    for role in pack.roles:
        scan(f"roles.{role.key}.record_kinds", role.record_kinds)
        scan(f"roles.{role.key}.motive_types", role.motive_types)
    for method in pack.method_defs:
        for trace in method.traces:
            path = f"method_defs.{method.key}.traces[{trace.kind}].location_kinds"
            scan(path, trace.location_kinds)
    for record in pack.record_defs:
        scan(f"record_defs.{record.key}.location_kinds", record.location_kinds)
    return out


def check(pack: Pack) -> list[PackIssue]:
    return [
        *_leaks(pack),
        *_trace_skew(pack),
        *_role_collisions(pack),
        *name_problems(pack),
        *duplicate_problems(pack),
    ]
