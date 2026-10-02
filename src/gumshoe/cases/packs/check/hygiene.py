"""Stage 4: label hygiene and leak rules (spec 4.4). A candidate's distinctive label tokens
may appear only in its own entries, and a motive's secret never reuses its own label."""

from collections.abc import Iterator
from fractions import Fraction

from gumshoe.cases.core.labels import distinctive, token_set
from gumshoe.cases.core.text import tokens
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.lint import SAMPLES, render, template_items
from gumshoe.cases.packs.issues import PackIssue

LENGTH_TOLERANCE = Fraction(1, 5)  # 20%


def _candidates(pack: Pack) -> dict[str, frozenset[str]]:
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
    """(path, text, owner): owner is the candidate id a text belongs to, if any."""
    owners = {}
    for method in pack.method_defs:
        for trace in method.traces:
            for i in range(len(trace.templates)):
                path = f"method_defs.{method.key}.traces[{trace.kind}].templates[{i}]"
                owners[path] = f"method:{method.key}"
    for motive in pack.motive_defs:
        for i in range(len(motive.secrets)):
            owners[f"motive_defs.{motive.key}.secrets[{i}]"] = f"motive:{motive.key}"
    for path, text in template_items(pack):
        yield path, text, owners.get(path)
    for location in pack.location_defs:
        for i, entry in enumerate(location.names):
            yield f"location_defs.{location.key}.names[{i}]", entry.text, None
    for role in pack.roles:
        for i, entry in enumerate(role.names):
            yield f"roles.{role.key}.names[{i}]", entry.text, None
        for i, trait in enumerate(role.traits):
            yield f"roles.{role.key}.traits[{i}]", trait, None
    for slot in pack.slot_defs:
        yield f"slot_defs[{slot.key}]", f"{slot.at} {slot.during}", None


def _leaks(pack: Pack) -> list[PackIssue]:
    candidates = _candidates(pack)
    out: list[PackIssue] = []
    for path, text, owner in _texts(pack):
        # placeholder names ({place.in}) are syntax, not prose: render with no values
        words = set(tokens(render(text, {})))
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


def check(pack: Pack) -> list[PackIssue]:
    return [*_leaks(pack), *_trace_skew(pack)]
