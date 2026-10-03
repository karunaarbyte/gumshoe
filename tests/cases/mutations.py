"""Table of deliberate defects: each names its catalogue code and the full expected cascade."""

from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import patch

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Claim, Effect, Event, Fact, PackRef, SourceRef
from gumshoe.cases.model.enums import Axis, ClaimKind, EffectKind, FactKind, SourceKind
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS
from gumshoe.cases.validate import runner
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Issue, Profile, Report
from tests.cases.fixtures import (
    TINY_PRESETS,
    build_case,
    build_pack,
    build_strict_case,
    record,
    search,
)
from tests.cases.helpers import (
    add_fact,
    drop_fact,
    replace_fact,
    replace_in,
    replace_limits,
    replace_record_source,
    replace_spec,
    replace_start,
    replace_truth,
)

WHO, HOW, WHY = Axis.WHO, Axis.HOW, Axis.WHY
RULES_OUT, SUPPORTS, PROVES = EffectKind.RULES_OUT, EffectKind.SUPPORTS, EffectKind.PROVES


@dataclass(frozen=True)
class Mutation:
    code: str  # the catalogue code this mutation targets
    apply: Callable[[Case], Case]
    expected: frozenset[str]  # the FULL expected code set (target plus declared cascade)
    profile: Profile = Profile.CUSTOM
    strict: bool = False  # start from the strict fixture and validate against the tiny pack
    crash_group: int | None = None  # make this group's runner raise (tests the runner guard)
    with_pack: bool = True  # strict mutations validate against the pack unless this is False
    apply_pair: Callable[[Case, Pack], tuple[Case, Pack]] | None = None  # change case AND pack


MUTATIONS: dict[str, Mutation] = {}


def mutation(
    code: str,
    apply: Callable[[Case], Case],
    expected: set[str] | None = None,
    *,
    profile: Profile = Profile.CUSTOM,
    strict: bool = False,
    crash_group: int | None = None,
    with_pack: bool = True,
) -> None:
    assert code in CATALOGUE, f"unknown code {code}"
    assert code not in MUTATIONS, f"duplicate mutation for {code}"
    wanted = frozenset(expected if expected is not None else {code})
    MUTATIONS[code] = Mutation(code, apply, wanted, profile, strict, crash_group, with_pack)


def pair_mutation(
    code: str,
    apply_pair: Callable[[Case, Pack], tuple[Case, Pack]],
    expected: set[str] | None = None,
) -> None:
    assert code in CATALOGUE and code not in MUTATIONS
    wanted = frozenset(expected if expected is not None else {code})
    MUTATIONS[code] = Mutation(
        code, lambda c: c, wanted, Profile.STRICT, True, None, True, apply_pair
    )


# A second mutation for a code whose MUTATIONS entry covers another branch of the same rule. Kept
# apart so MUTATIONS stays one entry per catalogue code (several tests rely on that).
VARIANTS: dict[str, Mutation] = {}


def pair_variant(
    name: str,
    code: str,
    apply_pair: Callable[[Case, Pack], tuple[Case, Pack]],
    expected: set[str] | None = None,
) -> None:
    assert code in CATALOGUE and name not in VARIANTS
    wanted = frozenset(expected if expected is not None else {code})
    VARIANTS[name] = Mutation(
        code, lambda c: c, wanted, Profile.STRICT, True, None, True, apply_pair
    )


def _boom(ctx: object) -> list[Issue]:
    raise RuntimeError("deliberate crash")


def run_mutation(m: Mutation) -> Report:
    case = m.apply(build_strict_case() if m.strict else build_case())
    pack = build_pack() if m.strict else None
    if m.apply_pair is not None and pack is not None:
        case, pack = m.apply_pair(case, pack)
    with patch.dict(runner.RUNNERS, {m.crash_group: _boom} if m.crash_group else {}):
        if m.strict:
            return runner.validate(case, pack if m.with_pack else None, m.profile, TINY_PRESETS)
        return runner.validate(case, None, m.profile, PRESETS)


def implemented_codes() -> frozenset[str]:
    groups = set(runner.RUNNERS) | {0}  # group 0: the runner's own crash guard
    return frozenset(code for code, spec in CATALOGUE.items() if spec.group in groups)


def _fact(fact_id: str, **overrides: object) -> Fact:
    base: dict[str, object] = {"id": fact_id, "kind": FactKind.CLUE, "source": search("l_study")}
    base.update(overrides)
    return Fact(**base)


def _effect(axis: Axis, candidate: str, kind: EffectKind) -> Effect:
    return Effect(axis=axis, candidate=candidate, kind=kind)


# ---- group 1: structure ---------------------------------------------------------------------

mutation("DUPLICATE_ID", lambda c: add_fact(c, c.facts[0].model_copy()))
mutation(
    "BAD_ID",
    lambda c: c.model_copy(
        update={
            "timeline": (
                *c.timeline,
                Event(id="T BAD!", slot=1, actor="s_anna", place="l_study", action="present"),
            )
        }
    ),
)
mutation("DANGLING_REF", lambda c: replace_fact(c, "f_key", requires=("f_missing",)))
mutation("TRUTH_NOT_CANDIDATE", lambda c: replace_truth(c, who="s_nobody"))
mutation("COUNT_MISMATCH", lambda c: replace_spec(c, suspects=4))
mutation(
    "EFFECT_WRONG_AXIS",
    lambda c: replace_fact(c, "f_sup_poison", effects=(_effect(WHO, "m_poison", SUPPORTS),)),
)
mutation(
    "MULTI_AXIS_PROVES",
    lambda c: replace_fact(
        c,
        "f_trace_poison",
        effects=(_effect(HOW, "m_poison", PROVES), _effect(WHO, "s_boris", PROVES)),
    ),
)
mutation(
    "TRACE_KIND_ON_NON_TRACE",
    lambda c: replace_fact(c, "f_key", trace_kind="residue"),
)
mutation("START_PROVES", lambda c: replace_start(c, facts=("f_proof_boris",)))
mutation("SLOTS_TOO_FEW", lambda c: replace_spec(c, slots=3))
mutation("SLOT_OUT_OF_RANGE", lambda c: replace_in(c, "timeline", "t_anna_2", slot=9))
mutation(
    "UNDECLARED_RECORD_SOURCE",
    lambda c: replace_fact(c, "f_sup_rope", source=record("gate_log", "l_cellar")),
)
mutation(
    "SOURCE_SHAPE",
    lambda c: replace_fact(
        c,
        "f_key",
        source=SourceRef.model_construct(
            kind=SourceKind.SEARCH, target="l_garden", subject="s_anna"
        ),
    ),
)
mutation(
    "TOO_LARGE",
    lambda c: c.model_copy(update={"facts": (*c.facts, *(_fact(f"f_x{i}") for i in range(200)))}),
)

# ---- group 0: the runner's crash guard ------------------------------------------------------

mutation("INTERNAL_ERROR", lambda c: c, crash_group=2)


# ---- group 2: labels ------------------------------------------------------------------------

mutation(
    "LABEL_DUPLICATE",
    lambda c: replace_in(
        c, "methods", "m_dagger", label="strangled with a rope", aliases=("knife",)
    ),
)
mutation(
    "LABEL_OVERLAP",
    lambda c: replace_in(
        replace_in(c, "methods", "m_rope", label="poison"), "methods", "m_poison", aliases=()
    ),
)
mutation(
    "ALIAS_COLLISION", lambda c: replace_in(c, "methods", "m_dagger", aliases=("knife", "rope"))
)
mutation(
    "LABEL_NAME_COLLISION",
    lambda c: replace_in(c, "motives", "v_debt", label="to cover a debt owed to Boris"),
)
mutation(
    "LABEL_LENGTH_SKEW",
    lambda c: replace_in(
        replace_in(c, "motives", "v_jealousy", label="jealousy"),
        "motives",
        "v_debt",
        label="to cover a truly enormous and ruinous gambling debt incurred over many long years",
    ),
)
mutation(
    "NO_DISTINCTIVE_TOKEN",
    lambda c: replace_in(c, "methods", "m_poison", label="dagger rope", aliases=()),
)


# ---- group 3: graph -------------------------------------------------------------------------

mutation(
    "DEPENDENCY_CYCLE",
    lambda c: replace_fact(
        replace_fact(c, "f_absent_dagger", requires=("f_absent_rope",)),
        "f_absent_rope",
        requires=("f_absent_dagger",),
    ),
)


# ---- group 4: reachability ------------------------------------------------------------------


def _orphan_the_garden(c: Case) -> Case:
    c = replace_in(c, "locations", "l_garden", decorative=True)
    c = replace_in(c, "locations", "l_cellar", decorative=True)
    return replace_start(c, locations=("l_study",))


mutation("ORPHAN_FACT", _orphan_the_garden)


mutation(
    "ORPHAN_ENTITY",
    lambda c: replace_start(c, suspects=("s_anna", "s_boris")),
    {"ORPHAN_ENTITY", "ORPHAN_FACT", "NO_STATEMENT"},
)
mutation("SOURCE_CAP_EXCEEDED", lambda c: add_fact(c, _fact("f_extra")))
mutation(
    "UNTOUCHABLE_CANDIDATE",
    lambda c: drop_fact(drop_fact(c, "f_absent_rope"), "f_sup_rope"),
)
mutation(
    "NO_STATEMENT",
    lambda c: replace_in(
        drop_fact(drop_fact(c, "f_lie_clara"), "f_sup_anna"), "suspects", "s_clara", knows=()
    ),
)
mutation(
    "EMPTY_LOCATION",
    lambda c: replace_fact(c, "f_clara_keys", source=search("l_garden")),
)
mutation(
    "GATE_ON_OWN_LIE",
    lambda c: replace_record_source(c, "ledger", "s_anna", requires=("f_lie_anna",)),
    {"GATE_ON_OWN_LIE", "EXPOSER_DEPENDS_ON_LIE"},
)


# ---- group 5: lies --------------------------------------------------------------------------

mutation("LIE_NO_CLAIM", lambda c: replace_fact(c, "f_lie_anna", claim=None))
mutation("LIE_NO_SPEAKER", lambda c: replace_fact(c, "f_lie_anna", speaker=None))
mutation("EXPOSER_MISSING", lambda c: replace_fact(c, "f_lie_anna", exposed_by=()))
mutation("EXPOSER_IS_LIE", lambda c: replace_fact(c, "f_lie_anna", exposed_by=("f_lie_boris",)))
mutation(
    "EXPOSER_OWNED_BY_SPEAKER", lambda c: replace_fact(c, "f_lie_anna", exposed_by=("f_sup_boris",))
)


def _exposer_depends_on_lie(c: Case) -> Case:
    c = add_fact(c, _fact("f_exp_anna", source=search("l_garden"), requires=("f_lie_anna",)))
    return replace_fact(
        c, "f_lie_anna", exposed_by=("f_exp_anna",), exposure_hook=search("l_garden")
    )


mutation("EXPOSER_DEPENDS_ON_LIE", _exposer_depends_on_lie)


def _exposer_unreachable(c: Case) -> Case:
    c = replace_fact(c, "f_secret_anna", requires=("f_clara_keys",))
    return replace_start(c, locations=("l_study",))


mutation(
    "EXPOSER_UNREACHABLE",
    _exposer_unreachable,
    {"EXPOSER_UNREACHABLE", "ORPHAN_ENTITY", "ORPHAN_FACT"},
)
mutation(
    "HOOK_MISMATCH",
    lambda c: replace_fact(c, "f_lie_anna", exposure_hook=record("ledger", "s_boris")),
)


# ---- group 6: solvability -------------------------------------------------------------------

mutation(
    "TRUTH_RULED_OUT",
    lambda c: replace_fact(c, "f_sup_boris", effects=(_effect(WHO, "s_boris", RULES_OUT),)),
    {"TRUTH_RULED_OUT", "SHAPE_MISMATCH"},
)
mutation(
    "WRONG_SURVIVES",
    lambda c: replace_fact(c, "f_absent_dagger", effects=()),
    {"WRONG_SURVIVES", "SHAPE_MISMATCH"},
)
mutation(
    "NO_POSITIVE_EVIDENCE",
    lambda c: replace_fact(c, "f_trace_poison", effects=()),
    {"NO_POSITIVE_EVIDENCE", "SHAPE_MISMATCH"},
)
mutation(
    "NO_ROUTE",
    lambda c: replace_fact(
        replace_fact(c, "f_trace_poison", effects=()), "f_absent_dagger", effects=()
    ),
    {"NO_ROUTE", "WRONG_SURVIVES", "NO_POSITIVE_EVIDENCE", "SHAPE_MISMATCH"},
)


# ---- group 7: timeline ----------------------------------------------------------------------

mutation(
    "DOUBLE_BOOKED",
    lambda c: c.model_copy(
        update={
            "timeline": (
                *c.timeline,
                Event(id="t_dup", slot=2, actor="s_anna", place="l_study", action="present"),
            )
        }
    ),
)
mutation("NO_CRIME_EVENT", lambda c: replace_in(c, "timeline", "t_crime", action="present"))
mutation("MULTIPLE_CRIME_EVENTS", lambda c: replace_in(c, "timeline", "t_clara_2", action="crime"))
mutation(
    "CULPRIT_NO_OPPORTUNITY",
    lambda c: replace_in(c, "timeline", "t_crime", actor="s_clara"),
    {"CULPRIT_NO_OPPORTUNITY", "LIE_CONSISTENT_WITH_TIMELINE"},
)
mutation(
    "OPPORTUNITY_NOT_RULED_OUT",
    lambda c: replace_fact(c, "f_clara_keys", effects=()),
    {"OPPORTUNITY_NOT_RULED_OUT", "WRONG_SURVIVES", "SHAPE_MISMATCH"},
)
mutation(
    "CLAIM_CONTRADICTS_TIMELINE",
    lambda c: replace_fact(
        c,
        "f_alibi_anna",
        claim=Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=2, place="l_study"),
    ),
    {"CLAIM_CONTRADICTS_TIMELINE", "ALIBI_NOT_ELSEWHERE"},
)
mutation(
    "LIE_CONSISTENT_WITH_TIMELINE",
    lambda c: replace_fact(
        c,
        "f_lie_anna",
        claim=Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=2, place="l_garden"),
    ),
)
mutation(
    "ALIBI_NOT_ELSEWHERE",
    lambda c: replace_fact(
        c,
        "f_alibi_anna",
        claim=Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=1, place="l_garden"),
    ),
)


# ---- group 8: difficulty --------------------------------------------------------------------

mutation("SOLUTION_SIZE_RANGE", lambda c: replace_limits(c, solution_min=5))
mutation("DEPTH_RANGE", lambda c: replace_limits(c, depth_min=1))
mutation("ACTIONS_RANGE", lambda c: replace_limits(c, actions_min=5))
mutation("DECISIVE_RATIO", lambda c: replace_limits(c, decisive_pct_max=10))


def _shared_gate(c: Case) -> Case:
    c = replace_fact(c, "f_trace_poison", requires=("f_key",))
    return replace_fact(c, "f_absent_dagger", requires=("f_key",))


mutation("SINGLE_POINT_OF_FAILURE", _shared_gate)


# ---- group 9: fairness ----------------------------------------------------------------------


def _extra_who_fact(fact_id: str, candidate: str, source: SourceRef) -> Fact:
    return _fact(fact_id, source=source, effects=(_effect(WHO, candidate, SUPPORTS),))


def _anna_has_more(c: Case) -> Case:
    c = add_fact(c, _extra_who_fact("f_x1", "s_anna", search("l_garden")))
    return add_fact(c, _extra_who_fact("f_x2", "s_anna", search("l_garden")))


mutation("FACTS_UNEVEN", _anna_has_more, {"FACTS_UNEVEN", "SHAPE_MISMATCH"})


def _anna_has_no_lie(c: Case) -> Case:
    c = drop_fact(c, "f_lie_anna")
    c = replace_in(c, "suspects", "s_anna", knows=("f_sup_boris",))
    return replace_spec(c, fairness_tolerance=0)


_UNEVEN = {"FACTS_UNEVEN", "LIES_UNEVEN", "EXPOSURES_UNEVEN"}
mutation("LIES_UNEVEN", _anna_has_no_lie, _UNEVEN)
mutation("EXPOSURES_UNEVEN", _anna_has_no_lie, _UNEVEN)
mutation(
    "CULPRIT_UNIQUE_EXTREME",
    lambda c: add_fact(c, _extra_who_fact("f_x3", "s_boris", search("l_garden"))),
    {"CULPRIT_UNIQUE_EXTREME", "SHAPE_MISMATCH"},
)
mutation(
    "SHAPE_MISMATCH",
    lambda c: replace_fact(c, "f_sup_anna", source=search("l_garden")),
)
mutation("TRUTH_DEPTH_EXTREME", lambda c: replace_fact(c, "f_trace_poison", requires=("f_key",)))


# ---- group 10: persona and secrets ----------------------------------------------------------

mutation("SECRET_FACT_MISSING", lambda c: replace_in(c, "suspects", "s_anna", secret_fact=""))
mutation(
    "SECRET_SOURCE_MISMATCH",
    lambda c: replace_in(c, "suspects", "s_anna", secret_fact="f_secret_boris"),
)
mutation(
    "KNOWS_NOT_SPEAKABLE",
    lambda c: replace_in(
        c, "suspects", "s_anna", knows=("f_lie_anna", "f_sup_boris", "f_sup_clara")
    ),
)
mutation("MOTIVE_MAPPING", lambda c: replace_in(c, "suspects", "s_anna", motive="v_debt"))


# ---- group 11: pack-bound rules (strict fixture + tiny pack) -------------------------------


def _rehash(case: Case, pack: Pack) -> Case:
    return case.model_copy(
        update={"pack_ref": PackRef(id=pack.id, skeleton_hash=pack.skeleton_hash())}
    )


mutation("PACK_RULES_SKIPPED", lambda c: c, strict=True, profile=Profile.STRICT, with_pack=False)
mutation(
    "PACK_MISMATCH",
    lambda c: c.model_copy(update={"pack_ref": PackRef(id="tiny", skeleton_hash="0" * 64)}),
    strict=True,
    profile=Profile.STRICT,
)
mutation(
    "SPEC_MISMATCH", lambda c: replace_spec(c, source_cap=5), strict=True, profile=Profile.STRICT
)


def _small_pack(case: Case, pack: Pack) -> tuple[Case, Pack]:
    pack = pack.model_copy(
        update={"capacity": pack.capacity.model_copy(update={"max_suspects": 2})}
    )
    return _rehash(case, pack), pack


pair_mutation("PACK_CAPACITY", _small_pack, {"PACK_CAPACITY", "SPEC_MISMATCH"})


def _overload_search(case: Case, pack: Pack) -> tuple[Case, Pack]:
    extra = tuple(_fact(f"f_pad{i}", source=search("l_cellar")) for i in range(3))
    return case.model_copy(update={"facts": (*case.facts, *extra)}), pack


pair_mutation("PACK_SOURCE_KIND_CAPACITY", _overload_search)
mutation(
    "SCENE_NOT_IN_PACK",
    lambda c: c.model_copy(update={"scene_type": "no_such_scene"}),
    strict=True,
    profile=Profile.STRICT,
)


def _forbid_poison(case: Case, pack: Pack) -> tuple[Case, Pack]:
    scene = pack.scene_types[0].model_copy(update={"allowed_methods": ("dagger", "rope")})
    pack = pack.model_copy(update={"scene_types": (scene,)})
    return _rehash(case, pack), pack


pair_mutation("SCENE_METHOD_NOT_ALLOWED", _forbid_poison)
mutation(
    "ROLE_UNKNOWN",
    lambda c: replace_in(c, "suspects", "s_anna", role="butler"),
    strict=True,
    profile=Profile.STRICT,
)


def _steward_no_debt(case: Case, pack: Pack) -> tuple[Case, Pack]:
    roles = tuple(
        r.model_copy(update={"motive_types": ("inheritance", "jealousy")})
        if r.key == "steward"
        else r
        for r in pack.roles
    )
    pack = pack.model_copy(update={"roles": roles})
    return _rehash(case, pack), pack


pair_mutation("ROLE_MOTIVE_NOT_ALLOWED", _steward_no_debt)


def _cook_no_ledger(case: Case, pack: Pack) -> tuple[Case, Pack]:
    roles = tuple(
        r.model_copy(update={"record_kinds": ("gate_log",)}) if r.key == "cook" else r
        for r in pack.roles
    )
    pack = pack.model_copy(update={"roles": roles})
    return _rehash(case, pack), pack


pair_mutation("ROLE_RECORD_KIND_NOT_ALLOWED", _cook_no_ledger)

mutation(
    "LOCATION_KIND_NOT_IN_PACK",
    lambda c: replace_in(c, "locations", "l_cellar", kind="dungeon"),
    strict=True,
    profile=Profile.STRICT,
)
mutation(
    "LOCATION_KIND_NOT_IN_SCENE",
    lambda c: replace_in(c, "locations", "l_study", kind="garden"),
    strict=True,
    profile=Profile.STRICT,
)
mutation(
    "TRACE_KIND_NOT_ALLOWED",
    lambda c: replace_fact(c, "f_trace_poison", trace_kind="blood"),
    strict=True,
    profile=Profile.STRICT,
)


def _no_residue_in_study(case: Case, pack: Pack) -> tuple[Case, Pack]:
    """The poison trace f_trace_poison is found at l_study, where its kind cannot occur."""
    methods = tuple(
        m.model_copy(
            update={
                "traces": tuple(
                    t.model_copy(
                        update={
                            "location_kinds": tuple(k for k in t.location_kinds if k != "study")
                        }
                    )
                    for t in m.traces
                )
            }
        )
        if m.key == "poison"
        else m
        for m in pack.method_defs
    )
    pack = pack.model_copy(update={"method_defs": methods})
    return _rehash(case, pack), pack


pair_variant("TRACE_KIND_NOT_ALLOWED:location", "TRACE_KIND_NOT_ALLOWED", _no_residue_in_study)
mutation(
    "TRACE_KIND_MISSING",
    lambda c: replace_fact(c, "f_trace_poison", trace_kind=None),
    strict=True,
    profile=Profile.STRICT,
)


def _drop_ledger(case: Case, pack: Pack) -> tuple[Case, Pack]:
    pack = pack.model_copy(
        update={
            "record_kinds": ("gate_log",),
            "record_defs": tuple(d for d in pack.record_defs if d.key != "ledger"),
        }
    )
    return _rehash(case, pack), pack


pair_mutation("RECORD_KIND_NOT_IN_PACK", _drop_ledger)


def _ledger_claim(case: Case, pack: Pack) -> tuple[Case, Pack]:
    claim = Claim(kind=ClaimKind.RECORD_REF, actor="s_anna", slot=2, record_kind="ledger")
    # a bare fact: no effects, no timeline_ref; l_cellar is the one search source under the cap
    case = add_fact(case, _fact("f_ledger_claim", claim=claim, source=search("l_cellar")))
    defs = tuple(
        d.model_copy(update={"subject": "location"}) if d.key == "ledger" else d
        for d in pack.record_defs
    )
    pack = pack.model_copy(update={"record_defs": defs})
    return _rehash(case, pack), pack


pair_mutation("CLAIM_SUBJECT_MISMATCH", _ledger_claim)
