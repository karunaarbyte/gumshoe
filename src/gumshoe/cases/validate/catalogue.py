"""The issue-code catalogue: every code the validator can emit, declared once."""

from dataclasses import dataclass

from gumshoe.cases.core.enums import FixStage as F
from gumshoe.cases.validate.report import HintOp as H
from gumshoe.cases.validate.report import Severity

E, W, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO


@dataclass(frozen=True)
class IssueSpec:
    code: str
    group: int
    fix_stage: F
    hint: H
    severity_strict: Severity
    severity_imported: Severity
    spoiler: bool
    requires_pack: bool
    message: str


def _row(
    code: str,
    group: int,
    stage: F,
    hint: H,
    message: str,
    *,
    strict: Severity = E,
    imported: Severity | None = None,
    spoiler: bool = False,
    pack: bool = False,
) -> IssueSpec:
    return IssueSpec(
        code,
        group,
        stage,
        hint,
        strict,
        strict if imported is None else imported,
        spoiler,
        pack,
        message,
    )


_ROWS = [
    # group 0: the validator itself
    _row("INTERNAL_ERROR", 0, F.NONE, H.NONE, "a rule group crashed on this input"),
    # group 1: structure
    _row("DUPLICATE_ID", 1, F.ASSEMBLE, H.RENAME_ID, "an id is used by more than one entity"),
    _row("BAD_ID", 1, F.ASSEMBLE, H.RENAME_ID, "an id does not match the id format"),
    _row(
        "DANGLING_REF", 1, F.ASSEMBLE, H.FIX_REF, "a reference points at an id that does not exist"
    ),
    _row(
        "TRUTH_NOT_CANDIDATE",
        1,
        F.TRUTH,
        H.FIX_REF,
        "the truth is not among the candidates of its axis",
        spoiler=True,
    ),
    _row("COUNT_MISMATCH", 1, F.ROSTER, H.ADJUST_COUNT, "an entity count differs from the spec"),
    _row(
        "EFFECT_WRONG_AXIS",
        1,
        F.FACTS,
        H.REMOVE_EFFECT,
        "an effect names a candidate of a different axis",
    ),
    _row("MULTI_AXIS_PROVES", 1, F.FACTS, H.REMOVE_EFFECT, "a fact proves on more than one axis"),
    _row("START_PROVES", 1, F.FACTS, H.MOVE_FACT, "a fact known from the start proves something"),
    _row(
        "TRACE_KIND_ON_NON_TRACE",
        1,
        F.FACTS,
        H.FIX_REF,
        "a fact that is not a trace names a trace kind",
    ),
    _row("SLOTS_TOO_FEW", 1, F.TIMELINE, H.FIX_SPEC, "the spec has fewer than four time slots"),
    _row("SLOT_OUT_OF_RANGE", 1, F.TIMELINE, H.FIX_REF, "a slot is outside 0..spec.slots-1"),
    _row(
        "UNDECLARED_RECORD_SOURCE",
        1,
        F.PLACEMENT,
        H.FIX_REF,
        "a record source is not declared in the case",
    ),
    _row(
        "SOURCE_SHAPE", 1, F.PLACEMENT, H.FIX_REF, "a source ref has the wrong shape for its kind"
    ),
    _row("TOO_LARGE", 1, F.ROSTER, H.ADJUST_COUNT, "the case exceeds the size caps"),
    # group 2: labels
    _row(
        "LABEL_DUPLICATE", 2, F.ROSTER, H.RELABEL, "two candidates have the same normalised label"
    ),
    _row(
        "LABEL_OVERLAP",
        2,
        F.ROSTER,
        H.RELABEL,
        "two labels on one axis overlap (token subset or substring)",
    ),
    _row(
        "ALIAS_COLLISION",
        2,
        F.ROSTER,
        H.RELABEL,
        "an alias collides with another candidate's label or alias",
    ),
    _row(
        "LABEL_NAME_COLLISION",
        2,
        F.ROSTER,
        H.RELABEL,
        "a method or motive label uses a suspect-name token",
    ),
    _row(
        "LABEL_LENGTH_SKEW",
        2,
        F.ROSTER,
        H.RELABEL,
        "labels on an axis differ too much in length",
        imported=W,
    ),
    _row(
        "NO_DISTINCTIVE_TOKEN",
        2,
        F.ROSTER,
        H.RELABEL,
        "a candidate has no token no other candidate uses",
    ),
    # group 3: graph
    _row(
        "DEPENDENCY_CYCLE",
        3,
        F.GATING,
        H.BREAK_CYCLE,
        "the fact and gate dependencies contain a cycle",
    ),
    # group 4: reachability
    _row("ORPHAN_FACT", 4, F.GATING, H.MOVE_FACT, "a fact can never be discovered"),
    _row(
        "ORPHAN_ENTITY",
        4,
        F.GATING,
        H.MOVE_FACT,
        "a location, suspect or record source can never be reached",
    ),
    _row(
        "SOURCE_CAP_EXCEEDED", 4, F.PLACEMENT, H.MOVE_FACT, "a source holds more facts than the cap"
    ),
    _row(
        "UNTOUCHABLE_CANDIDATE",
        4,
        F.FACTS,
        H.ADD_FACT,
        "a candidate has no reachable fact touching it",
    ),
    _row("NO_STATEMENT", 4, F.FACTS, H.ADD_FACT, "a suspect has no reachable statement"),
    _row("EMPTY_LOCATION", 4, F.PLACEMENT, H.ADD_FACT, "a non-decorative location holds no fact"),
    _row(
        "GATE_ON_OWN_LIE",
        4,
        F.GATING,
        H.BREAK_CYCLE,
        "a suspect's record is gated behind that suspect's own lie",
    ),
    # group 5: lies
    _row("LIE_NO_CLAIM", 5, F.FACTS, H.ADD_FACT, "a lie has no structured claim"),
    _row("LIE_NO_SPEAKER", 5, F.FACTS, H.FIX_REF, "a lie has no speaker"),
    _row("EXPOSER_MISSING", 5, F.FACTS, H.ADD_EXPOSER, "a lie has no exposer"),
    _row("EXPOSER_IS_LIE", 5, F.FACTS, H.ADD_EXPOSER, "an exposer is itself a lie"),
    _row(
        "EXPOSER_OWNED_BY_SPEAKER",
        5,
        F.FACTS,
        H.ADD_EXPOSER,
        "an exposer comes from the lie's own speaker",
    ),
    _row(
        "EXPOSER_DEPENDS_ON_LIE", 5, F.GATING, H.BREAK_CYCLE, "an exposer needs the lie it exposes"
    ),
    _row("EXPOSER_UNREACHABLE", 5, F.GATING, H.MOVE_FACT, "an exposer can never be discovered"),
    _row(
        "HOOK_MISMATCH",
        5,
        F.FACTS,
        H.FIX_REF,
        "the exposure hook does not name an exposer's source",
    ),
    # group 6: solvability
    _row(
        "TRUTH_RULED_OUT",
        6,
        F.FACTS,
        H.REMOVE_EFFECT,
        "a truthful fact rules out the truth",
        spoiler=True,
    ),
    _row(
        "WRONG_SURVIVES",
        6,
        F.FACTS,
        H.ADD_FACT,
        "a wrong candidate is never ruled out",
        spoiler=True,
    ),
    _row(
        "NO_POSITIVE_EVIDENCE",
        6,
        F.FACTS,
        H.ADD_FACT,
        "the truth has no non-lie positive evidence",
        spoiler=True,
    ),
    _row(
        "NO_ROUTE",
        6,
        F.FACTS,
        H.ADD_FACT,
        "there is no proves or elimination route to the truth",
        spoiler=True,
    ),
    # group 7: timeline
    _row("DOUBLE_BOOKED", 7, F.TIMELINE, H.FIX_REF, "an actor is in two places in one slot"),
    _row("NO_CRIME_EVENT", 7, F.TIMELINE, H.ADD_FACT, "the timeline has no crime event"),
    _row(
        "MULTIPLE_CRIME_EVENTS",
        7,
        F.TIMELINE,
        H.FIX_REF,
        "the timeline has more than one crime event",
    ),
    _row(
        "CULPRIT_NO_OPPORTUNITY",
        7,
        F.TIMELINE,
        H.FIX_REF,
        "the culprit is not at the scene when the crime happens",
        spoiler=True,
    ),
    _row(
        "OPPORTUNITY_NOT_RULED_OUT",
        7,
        F.FACTS,
        H.ADD_FACT,
        "an innocent with opportunity has no truthful rule-out",
    ),
    _row(
        "CLAIM_CONTRADICTS_TIMELINE",
        7,
        F.FACTS,
        H.FIX_REF,
        "a truthful claim disagrees with the timeline",
    ),
    _row(
        "LIE_CONSISTENT_WITH_TIMELINE",
        7,
        F.FACTS,
        H.FIX_REF,
        "a lie's claim agrees with the timeline",
    ),
    _row(
        "ALIBI_NOT_ELSEWHERE",
        7,
        F.FACTS,
        H.FIX_REF,
        "an alibi does not place its subject elsewhere at the crime",
    ),
    # group 8: difficulty
    _row(
        "SOLUTION_SIZE_RANGE",
        8,
        F.GATING,
        H.ADJUST_COUNT,
        "the cheapest solution is outside the spec's size window",
    ),
    _row(
        "DEPTH_RANGE",
        8,
        F.GATING,
        H.RAISE_DEPTH,
        "the cheapest solution's gating depth is outside the window",
    ),
    _row(
        "ACTIONS_RANGE",
        8,
        F.PLACEMENT,
        H.MOVE_FACT,
        "the cheapest solution's action count is outside the window",
    ),
    _row("DECISIVE_RATIO", 8, F.FACTS, H.REMOVE_EFFECT, "too large a share of facts is decisive"),
    _row(
        "SINGLE_POINT_OF_FAILURE",
        8,
        F.FACTS,
        H.ADD_FACT,
        "losing one fact makes an axis undecidable",
        imported=W,
        spoiler=True,
    ),
    # group 9: fairness (warnings when imported)
    _row(
        "FACTS_UNEVEN",
        9,
        F.PLACEMENT,
        H.MOVE_FACT,
        "suspects own uneven numbers of facts",
        imported=W,
    ),
    _row("LIES_UNEVEN", 9, F.FACTS, H.ADD_FACT, "suspects have uneven numbers of lies", imported=W),
    _row(
        "EXPOSURES_UNEVEN",
        9,
        F.FACTS,
        H.ADD_EXPOSER,
        "suspects have uneven numbers of exposures",
        imported=W,
    ),
    _row(
        "CULPRIT_UNIQUE_EXTREME",
        9,
        F.FACTS,
        H.MOVE_FACT,
        "the culprit is the unique extreme on a feature",
        imported=W,
        spoiler=True,
    ),
    _row(
        "SHAPE_MISMATCH",
        9,
        F.FACTS,
        H.MOVE_FACT,
        "candidates on an axis have different evidence shapes",
        imported=W,
    ),
    _row(
        "TRUTH_DEPTH_EXTREME",
        9,
        F.GATING,
        H.RAISE_DEPTH,
        "the truth's evidence depth is the unique extreme",
        imported=W,
        spoiler=True,
    ),
    # group 10: persona and secrets
    _row("SECRET_FACT_MISSING", 10, F.FACTS, H.ADD_FACT, "a suspect has no secret fact"),
    _row(
        "SECRET_SOURCE_MISMATCH",
        10,
        F.PLACEMENT,
        H.MOVE_FACT,
        "a secret fact is not a record about its suspect",
    ),
    _row("KNOWS_NOT_SPEAKABLE", 10, F.FACTS, H.FIX_REF, "a suspect knows a fact they cannot speak"),
    _row("MOTIVE_MAPPING", 10, F.ROSTER, H.FIX_REF, "suspects do not map one-to-one onto motives"),
    # group 11: pack-bound
    _row(
        "PACK_RULES_SKIPPED",
        11,
        F.NONE,
        H.NONE,
        "pack-bound rules were skipped because no pack was supplied",
        imported=INFO,
    ),
    _row(
        "PACK_MISMATCH",
        11,
        F.PACK,
        H.FIX_PACK,
        "the case's pack reference does not match the supplied pack",
        pack=True,
    ),
    _row(
        "SPEC_MISMATCH",
        11,
        F.PACK,
        H.FIX_SPEC,
        "the case's spec is not the one derived from its preset and pack",
        pack=True,
    ),
    _row(
        "PACK_CAPACITY",
        11,
        F.PACK,
        H.ADJUST_COUNT,
        "a count exceeds the pack's capacity",
        pack=True,
    ),
    _row(
        "PACK_SOURCE_KIND_CAPACITY",
        11,
        F.PLACEMENT,
        H.MOVE_FACT,
        "a source kind is overloaded relative to its sources",
        pack=True,
    ),
    _row(
        "SCENE_NOT_IN_PACK",
        11,
        F.PACK,
        H.FIX_PACK,
        "the scene type is not defined by the pack",
        pack=True,
    ),
    _row(
        "SCENE_METHOD_NOT_ALLOWED",
        11,
        F.ROSTER,
        H.DROP_CANDIDATE,
        "a method is not possible at the scene type",
        pack=True,
    ),
    _row(
        "ROLE_UNKNOWN",
        11,
        F.ROSTER,
        H.FIX_PACK,
        "a suspect's role is not defined by the pack",
        pack=True,
    ),
    _row(
        "ROLE_MOTIVE_NOT_ALLOWED",
        11,
        F.ROSTER,
        H.FIX_PACK,
        "a suspect's motive type is not allowed for their role",
        pack=True,
    ),
    _row(
        "ROLE_RECORD_KIND_NOT_ALLOWED",
        11,
        F.ROSTER,
        H.FIX_PACK,
        "a suspect's secret record kind is not allowed for their role",
        pack=True,
    ),
    _row(
        "LOCATION_KIND_NOT_IN_PACK",
        11,
        F.ROSTER,
        H.FIX_PACK,
        "a location's kind is not defined by the pack",
        pack=True,
    ),
    _row(
        "LOCATION_KIND_NOT_IN_SCENE",
        11,
        F.ROSTER,
        H.FIX_PACK,
        "the crime location's kind is not allowed at the scene type",
        pack=True,
    ),
    _row(
        "TRACE_KIND_NOT_ALLOWED",
        11,
        F.FACTS,
        H.FIX_PACK,
        "a trace kind is not allowed at the scene type or at the place it is found",
        pack=True,
    ),
    _row(
        "TRACE_KIND_MISSING",
        11,
        F.FACTS,
        H.FIX_REF,
        "a trace fact names no trace kind",
        pack=True,
    ),
    _row(
        "RECORD_KIND_NOT_IN_PACK",
        11,
        F.PACK,
        H.FIX_PACK,
        "a record source or claim uses a record kind the pack does not define",
        pack=True,
    ),
    _row(
        "CLAIM_SUBJECT_MISMATCH",
        11,
        F.FACTS,
        H.FIX_REF,
        "a record claim is about a suspect but the pack's record kind has another subject",
        pack=True,
    ),
    _row(
        "RECORD_SUBJECT_MISMATCH",
        11,
        F.FACTS,
        H.FIX_PACK,
        "a record source's subject type does not match the pack's record kind",
        pack=True,
    ),
]

CATALOGUE: dict[str, IssueSpec] = {row.code: row for row in _ROWS}
assert len(CATALOGUE) == len(_ROWS), "duplicate issue code in the catalogue"
