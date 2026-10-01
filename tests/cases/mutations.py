"""Table of deliberate defects: each names its catalogue code and the full expected cascade."""

from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import patch

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Effect, Event, Fact, SourceRef
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind, SourceKind
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
    replace_fact,
    replace_in,
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


MUTATIONS: dict[str, Mutation] = {}


def mutation(
    code: str,
    apply: Callable[[Case], Case],
    expected: set[str] | None = None,
    *,
    profile: Profile = Profile.CUSTOM,
    strict: bool = False,
    crash_group: int | None = None,
) -> None:
    assert code in CATALOGUE, f"unknown code {code}"
    assert code not in MUTATIONS, f"duplicate mutation for {code}"
    wanted = frozenset(expected if expected is not None else {code})
    MUTATIONS[code] = Mutation(code, apply, wanted, profile, strict, crash_group)


def _boom(ctx: object) -> list[Issue]:
    raise RuntimeError("deliberate crash")


def run_mutation(m: Mutation) -> Report:
    base = build_strict_case() if m.strict else build_case()
    case = m.apply(base)
    with patch.dict(runner.RUNNERS, {m.crash_group: _boom} if m.crash_group else {}):
        if m.strict:
            return runner.validate(case, build_pack(), m.profile, TINY_PRESETS)
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
