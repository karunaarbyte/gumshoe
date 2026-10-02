import random
import time

import pytest

from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.engine import all_sources, gather, use_source
from gumshoe.cases.play.state import new_state
from gumshoe.cases.simulate.oracle import (
    SearchLimitExceeded,
    axis_decidable,
    judge,
    min_sources,
    read_everything,
    spof_axes,
    survivors,
)
from tests.cases.fixtures import build_case
from tests.cases.helpers import drop_fact
from tests.cases.mutations import MUTATIONS
from tests.cases.reference import random_gates


def test_reading_everything_finds_every_fact_of_the_fixture():
    ix = CaseIndex.of(build_case())
    assert read_everything(ix).held == frozenset(f.id for f in build_case().facts)


def test_the_fixture_is_solvable_by_honest_deduction_and_by_naming_the_truth():
    verdict = judge(build_case())
    assert verdict.single_survivor and verdict.can_win
    assert set(verdict.decidable_axes) == set(Axis)
    assert len(verdict.reach) == 22


def test_survivors_use_truthful_rule_outs_only():
    case = build_case()
    ix = CaseIndex.of(case)
    held = read_everything(ix).held
    # the lies rule out Anna, Boris and Clara; the oracle must ignore them
    assert survivors(ix, held, Axis.WHO) == frozenset({"s_boris"})
    assert survivors(ix, held, Axis.HOW) == frozenset({"m_poison"})
    assert survivors(ix, held, Axis.WHY) == frozenset({"v_debt"})


def test_losing_a_rule_out_breaks_the_single_survivor_check_but_not_a_proof():
    case = drop_fact(build_case(), "f_absent_rope")
    verdict = judge(case)
    assert not verdict.single_survivor
    ix = CaseIndex.of(case)
    # how is still decidable: f_trace_poison proves the method
    assert axis_decidable(ix, read_everything(ix).held, Axis.HOW)


def test_a_truthful_rule_out_of_the_truth_makes_the_axis_undecidable():
    broken = MUTATIONS["TRUTH_RULED_OUT"].apply(build_case())
    verdict = judge(broken)
    # the truthful f_sup_boris now rules out Boris, the truth: who is lost, how and why stand
    assert not verdict.single_survivor and verdict.decidable_axes == (Axis.HOW, Axis.WHY)


def test_min_sources_of_the_fixture_is_two():
    # one search of the study (proves who and how) plus Boris's ledger (proves why)
    assert min_sources(build_case()) == 2


def test_min_sources_is_none_when_no_play_can_decide_the_case():
    # decidability is not monotone in the held set: an early state looks decided, but the
    # truthful rule-out of the truth is found later, so no play can end decided
    assert min_sources(MUTATIONS["TRUTH_RULED_OUT"].apply(build_case())) is None


def test_the_search_limit_is_a_distinct_error():
    with pytest.raises(SearchLimitExceeded):
        min_sources(build_case(), node_limit=1)


def test_spof_axes_of_the_fixture_are_empty_for_every_non_start_fact():
    case = build_case()
    assert {f.id: spof_axes(case, f.id) for f in case.facts if f.id not in case.start.facts} == {
        f.id: frozenset() for f in case.facts if f.id not in case.start.facts
    }


def test_spof_axes_of_the_shared_gate_mutation_is_how_through_the_key():
    # f_trace_poison (the proof of poison) and f_absent_dagger (the dagger's rule-out) both
    # require f_key. Without f_key: no proof of poison and the dagger survives, so how cannot
    # be decided; who (f_proof_boris) and why (f_secret_boris) are proved without the key.
    # Dropping either gated fact alone leaves the other route to poison standing.
    case = MUTATIONS["SINGLE_POINT_OF_FAILURE"].apply(build_case())
    found = {
        f.id: axes
        for f in case.facts
        if f.id not in case.start.facts and (axes := spof_axes(case, f.id))
    }
    assert found == {"f_key": frozenset({Axis.HOW})}


def _assert_parity(case, limit: int, label: str) -> None:
    """Walk the states use_source reaches (breadth first, up to `limit`); at every step the BFS
    step engine.gather must land on the very same held set."""
    ix = CaseIndex.of(case)
    sources = all_sources(ix)
    start = new_state(case)
    seen, queue = {start.held}, [start]
    while queue and len(seen) < limit:
        state = queue.pop(0)
        for source in sources:
            nxt, _ = use_source(ix, state, source)
            assert gather(ix, state.held, source) == nxt.held, label
            if nxt.held not in seen:
                seen.add(nxt.held)
                queue.append(nxt)


def test_the_bfs_step_reaches_exactly_the_states_use_source_reaches():
    # 400 of the fixture's 1536 reachable states and 30 of each mutation (time budget)
    _assert_parity(build_case(), 400, "fixture")
    for code, m in sorted(MUTATIONS.items()):
        if not (m.strict or m.crash_group or m.apply_pair):
            _assert_parity(m.apply(build_case()), 30, code)


def test_min_sources_is_quick_on_a_random_layout():
    # layout 17 of seed 5 was the slowest of the agreement test's 80 (0.5 s with use_source)
    rng = random.Random(5)
    for _ in range(17):
        random_gates(build_case(), rng)
    case = random_gates(build_case(), rng)
    started = time.perf_counter()
    assert min_sources(case) == 4
    assert time.perf_counter() - started < 0.3
