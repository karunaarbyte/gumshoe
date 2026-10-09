"""Stage 8: skin inputs. Does the pack hold the wording for every fact the generator builds, and
is that wording shaped so that its count, length or form tells nothing about which text is true."""

from collections.abc import Sequence
from fractions import Fraction

from gumshoe.cases.core.labels import token_set
from gumshoe.cases.core.text import tokens
from gumshoe.cases.model.pack import FamilyDef, Pack
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.lint import SAMPLES, render
from gumshoe.cases.packs.issues import PackIssue

REQUIRED_KINDS = ("physical_proof", "physical_clear", "key", "contradiction", "intro")
MIN_CLUES = 3
MIN_HINTS = 3
MIN_ENTRIES = 3
MIN_VICTIMS = 6
MIN_SMALLTALK = 20
CANDIDATE_TOLERANCE = Fraction(1, 5)  # between candidates of one group: 20%
PAIR_TOLERANCE = Fraction(1, 10)  # between texts a player can compare: 10%


def _mean(texts: Sequence[str]) -> Fraction:
    """The mean rendered length; the sample is fixed, so the number is deterministic."""
    return Fraction(sum(len(render(t, SAMPLES[0])) for t in texts), len(texts))


def _fmt(value: Fraction) -> str:
    return f"{float(value):.1f}"


def _families(pack: Pack) -> list[PackIssue]:
    out: list[PackIssue] = []
    for kind in REQUIRED_KINDS:
        found = [f for f in pack.families if f.kind == kind]
        if not found:
            out.append(make("MISSING_FAMILY", f"families.{kind}", kind=kind))
        for extra in found[1:]:
            out.append(
                make("DUPLICATE_FAMILY_KIND", f"families.{extra.id}", kind=kind, count=len(found))
            )
    return out


def _too_few(path: str, count: int, needed: int) -> list[PackIssue]:
    if count >= needed:
        return []
    return [make("TOO_FEW_TEXTS", path, count=count, needed=needed)]


def _lengths(pack: Pack) -> list[PackIssue]:
    """Counts and lengths of the owned texts: every candidate of a group must look alike."""
    out: list[PackIssue] = []
    groups: dict[str, dict[str, list[str]]] = {
        "absent": {
            m.key: [t for tr in m.traces for t in tr.absent]
            for m in pack.method_defs
            if any(tr.absent for tr in m.traces)
        },
        "clues": {m.key: list(m.clues) for m in pack.method_defs if m.clues},
        "hints": {m.key: list(m.hints) for m in pack.motive_defs if m.hints},
    }
    for what, owned in groups.items():
        table = "motive_defs" if what == "hints" else "method_defs"
        every = pack.motive_defs if what == "hints" else pack.method_defs
        counts = {d.key: len(owned.get(d.key, [])) for d in every}
        target = max(counts.values(), default=0)
        if target:
            for key, count in sorted(counts.items()):
                if count < target:
                    out.append(
                        make(
                            "TEXT_COUNT_SKEW",
                            f"{table}.{key}.{what}",
                            what=what,
                            count=count,
                            target=target,
                        )
                    )
        means = {key: _mean(texts) for key, texts in owned.items()}
        if means:
            overall = sum(means.values(), Fraction(0)) / len(means)
            for key, mean in sorted(means.items()):
                if overall > 0 and abs(mean - overall) > overall * CANDIDATE_TOLERANCE:
                    out.append(
                        make(
                            "TEXT_LENGTH_SKEW",
                            f"{table}.{key}.{what}",
                            what=what,
                            mean=_fmt(mean),
                            against="the mean over candidates",
                            overall=_fmt(overall),
                            percent=20,
                        )
                    )
    absent = [t for m in pack.method_defs for tr in m.traces for t in tr.absent]
    templates = [t for m in pack.method_defs for tr in m.traces for t in tr.templates]
    if absent and templates:
        a, b = _mean(absent), _mean(templates)
        if abs(a - b) > b * PAIR_TOLERANCE:
            out.append(
                make(
                    "TEXT_LENGTH_SKEW",
                    "method_defs",
                    what="absent",
                    mean=_fmt(a),
                    against="the mean of the trace templates",
                    overall=_fmt(b),
                    percent=10,
                )
            )
    return out


def _pair(pack: Pack) -> list[PackIssue]:
    by_kind: dict[str, FamilyDef] = {}
    for family in pack.families:
        by_kind.setdefault(family.kind, family)
    proof, clear = by_kind.get("physical_proof"), by_kind.get("physical_clear")
    if proof is None or clear is None:
        return []
    path = f"families.{clear.id}"
    if len(proof.variants) != len(clear.variants):
        return [make("PAIR_COUNT_SKEW", path, proof=len(proof.variants), clear=len(clear.variants))]
    if not proof.variants:
        return []
    out: list[PackIssue] = []
    a, b = _mean(proof.variants), _mean(clear.variants)
    if abs(a - b) > max(a, b) * PAIR_TOLERANCE:
        out.append(
            make("PAIR_LENGTH_SKEW", path, reason=f"mean lengths {_fmt(a)} and {_fmt(b)} differ")
        )
    la = [len(render(t, SAMPLES[0])) for t in proof.variants]
    lb = [len(render(t, SAMPLES[0])) for t in clear.variants]
    if max(min(la), min(lb)) > min(max(la), max(lb)):
        out.append(
            make(
                "PAIR_LENGTH_SKEW",
                path,
                reason=f"length ranges {min(la)}-{max(la)} and {min(lb)}-{max(lb)} do not overlap",
            )
        )
    return out


def _smalltalk(pack: Pack) -> list[PackIssue]:
    banned: dict[str, str] = {}
    for kind, defs in (("method", pack.method_defs), ("motive", pack.motive_defs)):
        for d in defs:
            for token in token_set(d.label, *d.aliases):
                banned.setdefault(token, f"{kind}:{d.key}")
    for role in pack.roles:
        for token in token_set(role.noun, *(e.text for e in role.names)):
            banned.setdefault(token, f"role:{role.key}")
    out: list[PackIssue] = []
    seen: set[str] = set()
    for i, word in enumerate(pack.smalltalk_allow):
        path = f"meta.smalltalk_allow[{i}]"
        stems = tokens(word)
        if not word.isascii() or not word.isalpha() or not word.islower() or len(stems) != 1:
            out.append(make("BAD_SMALLTALK_WORD", path, word=word, reason="not one lowercase word"))
        elif word in seen:
            out.append(make("BAD_SMALLTALK_WORD", path, word=word, reason="listed twice"))
        elif stems[0] in banned:
            reason = f"a token of {banned[stems[0]]}"
            out.append(make("BAD_SMALLTALK_WORD", path, word=word, reason=reason))
        seen.add(word)
    return out


def check(pack: Pack) -> list[PackIssue]:
    out = _families(pack)
    for method in pack.method_defs:
        for trace in method.traces:
            base = f"method_defs.{method.key}.traces[{trace.kind}].absent"
            out += _too_few(base, len(trace.absent), len(trace.templates))
        out += _too_few(f"method_defs.{method.key}.clues", len(method.clues), MIN_CLUES)
    for motive in pack.motive_defs:
        out += _too_few(f"motive_defs.{motive.key}.hints", len(motive.hints), MIN_HINTS)
    for record in pack.record_defs:
        if record.subject == "location":
            out += _too_few(f"record_defs.{record.key}.entries", len(record.entries), MIN_ENTRIES)
    out += _too_few("victims", len(pack.victims), MIN_VICTIMS)
    out += _too_few("meta.smalltalk_allow", len(pack.smalltalk_allow), MIN_SMALLTALK)
    for i, victim in enumerate(pack.victims):
        if victim.pronoun is None or not victim.proper:
            out.append(
                make(
                    "ENTRY_INCOMPLETE",
                    f"victims[{i}]",
                    what="a victim needs a pronoun and proper = true",
                )
            )
    for role in pack.roles:
        if not role.style.strip():
            out.append(
                make("ENTRY_INCOMPLETE", f"roles.{role.key}.style", what="a role needs a style")
            )
    out += _lengths(pack)
    out += _pair(pack)
    out += _smalltalk(pack)
    return out
