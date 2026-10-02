"""Stage 3: template placeholders, rendering lints, variant counts and claim slots."""

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.lint import (
    KNOWN_PLACEHOLDERS,
    SAMPLES,
    article_mismatch,
    double_space,
    doubled_word,
    mid_sentence_capital,
    placeholders,
    render,
    stray_brace,
    template_items,
)
from gumshoe.cases.packs.issues import PackIssue
from gumshoe.cases.packs.suggest import did_you_mean

VARIANTS_STANDARD = 5
VARIANTS_LONG = 7  # the largest per-case count (spec 4.2)


def lint_template(path: str, text: str) -> list[PackIssue]:
    names = placeholders(text)
    out = [
        make("UNKNOWN_PLACEHOLDER", path, did_you_mean(n, KNOWN_PLACEHOLDERS), name=n)
        for n in sorted({n for n in names if n not in KNOWN_PLACEHOLDERS})
    ]
    if stray_brace(text):
        out.append(make("UNRESOLVED_BRACE", path))
    if out:
        return out  # rendering a broken template would only add noise
    word = mid_sentence_capital(text)
    if word:
        out.append(make("MID_SENTENCE_CAPITAL", path, word=word))
    seen: set[str] = set()
    for sample in SAMPLES:
        rendered = render(text, sample)
        doubled = doubled_word(rendered)
        if doubled and "DOUBLED_WORD" not in seen:
            seen.add("DOUBLED_WORD")
            out.append(make("DOUBLED_WORD", path, word=doubled))
        if double_space(rendered) and "DOUBLE_SPACE" not in seen:
            seen.add("DOUBLE_SPACE")
            out.append(make("DOUBLE_SPACE", path))
        phrase = article_mismatch(rendered)
        if phrase and "ARTICLE_MISMATCH" not in seen:
            seen.add("ARTICLE_MISMATCH")
            out.append(make("ARTICLE_MISMATCH", path, phrase=phrase))
    return out


def check(pack: Pack) -> list[PackIssue]:
    out: list[PackIssue] = []
    for path, text in template_items(pack):
        out += lint_template(path, text)
    needed = VARIANTS_LONG if "long" in pack.presets else VARIANTS_STANDARD
    for family in pack.families:
        base = f"families.{family.id}"
        if len(family.variants) < needed:
            out.append(make("TOO_FEW_VARIANTS", base, count=len(family.variants), needed=needed))
        for slot in family.claim_slots:
            if slot not in KNOWN_PLACEHOLDERS:
                out.append(
                    make(
                        "UNKNOWN_PLACEHOLDER",
                        f"{base}.claim_slots[{slot}]",
                        did_you_mean(slot, KNOWN_PLACEHOLDERS),
                        name=slot,
                    )
                )
                continue
            for i, variant in enumerate(family.variants):
                if slot not in placeholders(variant):
                    out.append(make("CLAIM_SLOT_MISSING", f"{base}.variants[{i}]", slot=slot))
    return out
