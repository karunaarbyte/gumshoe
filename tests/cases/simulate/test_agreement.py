"""Validator vs simulator. They share only the gate spec; a disagreement is a bug in one of them.

When a test here fails, do NOT weaken it: find which side is wrong (read the two code paths and
the plain rule in the spec), fix that side test-first, and record the finding in the commit."""

import random
from dataclasses import dataclass

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.simulate.oracle import (
    SearchLimitExceeded,
    judge,
    min_sources,
    read_everything,
    spof_axes,
)
from gumshoe.cases.validate import runner
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.reach import compute_reach
from gumshoe.cases.validate.report import Profile, Report, Severity
from gumshoe.cases.validate.routes import best_solution
from tests.cases.fixtures import build_case
from tests.cases.fuzz import corrupt
from tests.cases.mutations import MUTATIONS
from tests.cases.reference import naive_reach, random_gates

SOLVABILITY_CODES = {"TRUTH_RULED_OUT", "WRONG_SURVIVES", "NO_ROUTE"}


@dataclass
class Tally:
    """What the comparisons actually covered, so a silently skipped group cannot pass as green."""

    compared: int = 0  # group-1 clean, no crash: reachability compared
    compared_solvable: int = 0  # group 6 ran and was compared
    solvability_bad: int = 0  # ... and the validator flagged the case unsolvable
    spof_compared: int = 0  # group 8 ran and was compared
    spof_nonempty: int = 0  # ... and the two sides found at least one single point of failure


def report_of(case: Case) -> Report:
    return runner.validate(case, None, Profile.CUSTOM)


def group1_clean(report: Report) -> bool:
    return not any(i.group == 1 and i.severity is Severity.ERROR for i in report.issues)


def crashed(report: Report) -> bool:
    return any(i.code == "INTERNAL_ERROR" for i in report.issues)


def mutated_cases():
    for code, m in sorted(MUTATIONS.items()):
        if m.strict or m.crash_group or m.apply_pair:
            continue  # strict/pack/crash mutations exercise the validator machinery, not play
        yield code, m.apply(build_case())


def assert_agree(case: Case, label: str, tally: Tally, *, check_spof: bool = True) -> None:
    report = report_of(case)
    # ghost start ids make the engine's held set a superset of the validator's for a case that
    # group 1 already rejects, so only structurally sound cases are compared
    if not group1_clean(report) or crashed(report):
        return
    tally.compared += 1
    ix = CaseIndex.of(case)
    held = read_everything(ix).held
    # (1) reachability: play engine == validator fixpoint == naive reference
    assert held == compute_reach(ix).facts == naive_reach(case), f"{label}: reachability"
    verdict = judge(case)
    # (2) solvability: the validator's group 6 verdict == honest deduction by the oracle
    if 6 not in report.skipped_groups:
        tally.compared_solvable += 1
        validator_ok = not ({i.code for i in report.issues} & SOLVABILITY_CODES)
        tally.solvability_bad += not validator_ok
        assert validator_ok == verdict.single_survivor, f"{label}: solvability"
        if validator_ok:
            assert verdict.can_win, f"{label}: a solvable case must be winnable through play"
    # (3) single points of failure: same (fact, axis) pairs
    if check_spof and 8 not in report.skipped_groups:
        from_validator = {
            (i.subjects[0], i.axis) for i in report.issues if i.code == "SINGLE_POINT_OF_FAILURE"
        }
        from_oracle = {
            (f.id, axis)
            for f in case.facts
            if f.id not in case.start.facts
            for axis in spof_axes(case, f.id)
        }
        assert from_validator == from_oracle, f"{label}: single points of failure"
        tally.spof_compared += 1
        tally.spof_nonempty += bool(from_oracle)


def test_the_fixture_agrees_everywhere():
    tally = Tally()
    assert_agree(build_case(), "fixture", tally)
    assert (tally.compared_solvable, tally.spof_compared) == (1, 1)


def test_every_mutation_of_the_fixture_agrees_and_the_oracle_never_raises():
    seen = 0
    tally = Tally()
    for code, case in mutated_cases():
        judge(case)  # never raises, even on garbled cases
        assert_agree(case, f"mutation {code}", tally)
        seen += 1
    assert seen > 40
    assert tally.solvability_bad >= 4  # the unsolvable mutations really reach the comparison
    assert tally.spof_nonempty >= 1


def test_random_gate_layouts_agree_on_reachability_solvability_and_spof():
    rng = random.Random(20261002)
    tally = Tally()
    for step in range(300):
        assert_agree(random_gates(build_case(), rng), f"gates {step}", tally)
    assert tally.compared_solvable > 20
    assert tally.spof_compared > 20
    assert tally.spof_nonempty >= 1


def test_fuzzed_corruptions_agree_wherever_the_validator_ran_the_group():
    rng = random.Random(77)
    tally = Tally()
    for step in range(300):
        assert_agree(corrupt(build_case(), rng), f"fuzz {step}", tally, check_spof=False)
    assert tally.compared > 30  # the corruption mix really reaches the later groups


def test_the_cheapest_play_is_never_dearer_than_the_validators_cheapest_solution():
    ctx = Ctx(case=build_case(), pack=None, profile=Profile.CUSTOM)
    best = best_solution(ctx.index, ctx.graph, ctx.reach.facts)
    assert best is not None and best.actions == 2
    assert min_sources(build_case()) == 2 <= best.actions


def test_on_random_layouts_a_play_never_needs_more_uses_than_the_solution_has_facts():
    # (a fact chain inside one source can need two uses of it, so compare against fact count)
    rng = random.Random(5)
    checked = 0
    for _ in range(80):
        case = random_gates(build_case(), rng)
        ctx = Ctx(case=case, pack=None, profile=Profile.CUSTOM)
        best = best_solution(ctx.index, ctx.graph, ctx.reach.facts)
        if best is None:
            continue
        try:
            fewest = min_sources(case)
        except SearchLimitExceeded:
            continue
        if fewest is not None:
            checked += 1
            assert fewest <= best.size
    assert checked > 10
