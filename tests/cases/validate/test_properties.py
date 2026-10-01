import random

from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.reach import compute_reach
from tests.cases.fixtures import build_case
from tests.cases.reference import naive_ancestors, naive_reach, random_gates


def test_reachability_agrees_with_the_naive_reference_on_random_gate_layouts():
    rng = random.Random(20261001)
    for step in range(400):
        case = random_gates(build_case(), rng)
        assert compute_reach(CaseIndex.of(case)).facts == naive_reach(case), f"step {step}"


def test_removed_facts_agree_with_the_naive_reference_on_a_case_without_them():
    rng = random.Random(7)
    base = build_case()
    for step in range(150):
        case = random_gates(base, rng)
        victim = rng.choice([f.id for f in case.facts])
        fast = compute_reach(CaseIndex.of(case), removed=frozenset({victim})).facts
        slow = naive_reach(
            case.model_copy(update={"facts": tuple(f for f in case.facts if f.id != victim)})
        )
        # production marks the victim removed; the reference drops it: compare modulo the victim
        assert fast == slow - {victim}, f"step {step}"


def test_ancestors_and_cycle_detection_agree_with_the_naive_reference():
    rng = random.Random(99)
    cyclic = acyclic = 0
    for step in range(400):
        case = random_gates(build_case(), rng)
        graph = build_graph(CaseIndex.of(case))
        naive = naive_ancestors(case)
        if naive is None:
            cyclic += 1
            assert graph.cycle, f"step {step}: reference found a cycle the graph missed"
        else:
            acyclic += 1
            assert not graph.cycle and graph.anc == naive, f"step {step}"
    assert cyclic > 20 and acyclic > 20  # the generator really exercises both branches
