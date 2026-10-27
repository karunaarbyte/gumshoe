"""Every code the pack loader can emit, declared once. Names are plain and never collide with
the case catalogue (a test enforces it)."""

from dataclasses import dataclass

from gumshoe.cases.packs.issues import PackIssue, PackSeverity


@dataclass(frozen=True)
class PackIssueSpec:
    code: str
    stage: int
    severity: PackSeverity
    message: str  # str.format template over `params`
    params: tuple[str, ...]


def _row(code: str, stage: int, message: str, *params: str) -> PackIssueSpec:
    return PackIssueSpec(code, stage, PackSeverity.ERROR, message, params)


_ROWS = (
    # stage 1: schema
    _row("TOML_SYNTAX", 1, "the file is not valid TOML: {reason}", "reason"),
    _row("UNKNOWN_KEY", 1, "unknown key {key!r}", "key"),
    _row("WRONG_TYPE", 1, "wrong type or value: {reason}", "reason"),
    _row("MISSING_FIELD", 1, "required field {field!r} is missing", "field"),
    # stage 2: closed references
    _row("UNKNOWN_LOCATION_KIND", 2, "unknown location kind {name!r}", "name"),
    _row("UNKNOWN_RECORD_KIND", 2, "unknown record kind {name!r}", "name"),
    _row("UNKNOWN_TRACE_KIND", 2, "unknown trace kind {name!r}", "name"),
    _row("UNKNOWN_METHOD", 2, "unknown method {name!r}", "name"),
    _row("UNKNOWN_MOTIVE_TYPE", 2, "unknown motive type {name!r}", "name"),
    _row("DUPLICATE_KEY", 2, "the key {name!r} is defined more than once", "name"),
    # stage 3: templates
    _row("UNKNOWN_PLACEHOLDER", 3, "unknown placeholder {name!r}", "name"),
    _row("UNRESOLVED_BRACE", 3, "unbalanced or unresolved brace in the text"),
    _row("DOUBLED_WORD", 3, "doubled word {word!r} in the rendered text", "word"),
    _row("DOUBLE_SPACE", 3, "two spaces in a row in the rendered text"),
    _row("ARTICLE_MISMATCH", 3, "'a' or 'an' does not fit the next word ({phrase!r})", "phrase"),
    _row(
        "MID_SENTENCE_CAPITAL",
        3,
        "capitalised word {word!r} inside a sentence; use a placeholder for names",
        "word",
    ),
    _row(
        "TOO_FEW_VARIANTS",
        3,
        "family has {count} variants; needs at least {needed}",
        "count",
        "needed",
    ),
    _row("CLAIM_SLOT_MISSING", 3, "a variant lacks the claim slot {slot!r}", "slot"),
    # stage 4: label hygiene and leak rules
    _row(
        "LABEL_TOKEN_LEAK",
        4,
        "this text uses the token {token!r}, distinctive to candidate {candidate!r}",
        "token",
        "candidate",
    ),
    _row(
        "SECRET_REUSES_LABEL",
        4,
        "an owned text of {candidate!r}, a secret or a hint, reuses its own label token {token!r}",
        "candidate",
        "token",
    ),
    _row(
        "TRACE_COUNT_SKEW",
        4,
        "this method has {count} trace templates; the largest count is {target}",
        "count",
        "target",
    ),
    _row(
        "TRACE_LENGTH_SKEW",
        4,
        "mean trace length {mean} is more than 20% from the overall mean {overall}",
        "mean",
        "overall",
    ),
    _row(
        "ROLE_TOKEN_COLLISION",
        4,
        "a token ({token!r}) of this role's {what} is also used by {other!r}",
        "what",
        "token",
        "other",
    ),
    _row("ROLE_NO_NAME", 4, "the role has no name to give a suspect"),
    _row(
        "NAME_DUPLICATE",
        4,
        "the name {name!r} equals {other!r} (same text after Unicode normalisation and case)",
        "name",
        "other",
    ),
    _row("DUPLICATE_ENTRY", 4, "the list names {value!r} more than once", "value"),
    _row(
        "RECORD_KEY_INVALID",
        4,
        "the record kind key {key!r} must be lowercase letters, digits and underscores (1 to 30)",
        "key",
    ),
    # stage 5: plausibility
    _row("ROLE_NO_NOUN", 5, "the role has no display noun"),
    _row("ROLE_NO_RECORD_KIND", 5, "the role has no record kind"),
    _row("ROLE_NO_SUSPECT_RECORD", 5, "the role has no record kind about a suspect"),
    _row(
        "ROLE_TOO_FEW_MOTIVES",
        5,
        "the role allows {count} motive types; needs at least {needed}",
        "count",
        "needed",
    ),
    _row("MOTIVE_UNREACHABLE", 5, "no role allows this motive type"),
    _row("SCENE_NO_CRIME_LOCATION", 5, "the scene type has no location kind for the crime"),
    _row(
        "SCENE_MANY_CRIME_LOCATIONS",
        5,
        "the scene type lists {count} location kinds; the generator needs exactly one",
        "count",
    ),
    _row(
        "METHOD_TOO_RARE",
        5,
        "the method is allowed in {count} scene types; needs at least {needed}",
        "count",
        "needed",
    ),
    _row(
        "SCENE_METHOD_IMPOSSIBLE",
        5,
        "no trace of method {method!r} can be placed at scene type {scene!r}",
        "method",
        "scene",
    ),
    _row("RECORD_NO_NAME", 5, "the record kind has no display name"),
    _row("RECORD_NO_LOCATION_KIND", 5, "the record kind lists no location kind"),
    _row(
        "RECORD_EVENT_SUBJECT",
        5,
        "the record kind is about an event; the generator supports suspects and places only",
    ),
    _row("SLOT_DEFS_TOO_FEW", 5, "{defs} slot definitions for {slots} slots", "defs", "slots"),
    # stage 6: capacity and presets
    _row("PRESET_UNSUPPORTED", 6, "the pack cannot host this preset: {reason}", "reason"),
    _row(
        "PRESET_NOT_MONOTONE",
        6,
        "effective {size} drops from preset {previous!r} to {preset!r}",
        "size",
        "previous",
        "preset",
    ),
    _row(
        "PRESET_NO_DEPTH",
        6,
        "no gating depth fits the {preset!r} preset on this pack"
        " (record kinds, windows or source capacity rule out every depth)",
        "preset",
    ),
    _row(
        "CAPACITY_EXCEEDS_POOL",
        6,
        "capacity allows {capacity} {what} but the pack defines only {pool}",
        "what",
        "capacity",
        "pool",
    ),
    _row(
        "LOCATION_KINDS_TOO_FEW",
        6,
        "the pack defines {count} location kinds; needs at least {needed}",
        "count",
        "needed",
    ),
    # stage 7: motive matching
    _row(
        "NO_PERFECT_MATCHING",
        7,
        "no suspect-to-motive matching exists for roster {roster}",
        "roster",
    ),
    _row(
        "MOTIVE_TOO_PREDICTABLE",
        7,
        "in roster {roster} this role gets this motive {percent}% of the time; the cap is 50%",
        "roster",
        "percent",
    ),
    # stage 8: skin inputs
    _row("MISSING_FAMILY", 8, "the pack has no family of the required kind {kind!r}", "kind"),
    _row(
        "DUPLICATE_FAMILY_KIND",
        8,
        "{count} families carry the kind {kind!r}; a required kind needs exactly one",
        "count",
        "kind",
    ),
    _row(
        "TOO_FEW_TEXTS",
        8,
        "this list has {count} texts; needs at least {needed}",
        "count",
        "needed",
    ),
    _row("ENTRY_INCOMPLETE", 8, "{what}", "what"),
    _row(
        "TEXT_COUNT_SKEW",
        8,
        "this candidate has {count} {what}; the largest count is {target}",
        "what",
        "count",
        "target",
    ),
    _row(
        "TEXT_LENGTH_SKEW",
        8,
        "mean length of the {what} is {mean}; {against} is {overall} (allowed gap {percent}%)",
        "what",
        "mean",
        "against",
        "overall",
        "percent",
    ),
    _row(
        "TRACE_SHAPE_SKEW",
        8,
        "an absent text has {absent} {what} where its paired trace template has {template}",
        "what",
        "absent",
        "template",
    ),
    _row(
        "PAIR_COUNT_SKEW",
        8,
        "physical_proof has {proof} variants and physical_clear has {clear}",
        "proof",
        "clear",
    ),
    _row("PAIR_LENGTH_SKEW", 8, "the physical pair is shaped differently: {reason}", "reason"),
    _row(
        "BAD_SMALLTALK_WORD",
        8,
        "the small-talk entry {word!r} is not allowed: {reason}",
        "word",
        "reason",
    ),
)

PACK_CATALOGUE: dict[str, PackIssueSpec] = {spec.code: spec for spec in _ROWS}
assert len(PACK_CATALOGUE) == len(_ROWS), "duplicate pack code"


def make(code: str, path: str, suggestion: str = "", **params: object) -> PackIssue:
    spec = PACK_CATALOGUE[code]  # KeyError for an unknown code: checks cannot invent codes
    if set(params) != set(spec.params):
        raise ValueError(f"{code} takes {spec.params}, got {sorted(params)}")
    return PackIssue(
        code, spec.severity, spec.stage, path, spec.message.format(**params), suggestion
    )
