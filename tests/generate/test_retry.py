import random

import pytest

from gumshoe.cases.core.enums import FixStage
from gumshoe.cases.generate.gen_context import PIPELINE
from gumshoe.cases.generate.pipeline import RETRIES, Exhausted, Retry, earliest
from tests.generate import retry_model

N = {stage: i for i, stage in enumerate(PIPELINE)}


def test_a_fresh_retry_state_has_every_counter_at_zero():
    retry = Retry()
    assert retry.counters() == (0,) * len(PIPELINE) == (0,) * 8
    assert set(retry.k.values()) == {0}


def test_a_failure_restarts_its_stage_and_gives_every_later_stage_a_new_counter():
    retry = Retry()
    assert retry.fail("facts") == "facts"
    assert retry.counters() == (0, 0, 0, 1, 1, 1, 1, 1)
    assert retry.k["facts"] == 1 and sum(retry.k.values()) == 1
    assert retry.fail("timeline") == "timeline"  # an earlier stage resets the later retry counts
    assert retry.counters() == (0, 0, 1, 2, 2, 2, 2, 2)
    assert retry.k["timeline"] == 1 and retry.k["facts"] == 0


def test_the_sixth_failure_of_a_stage_restarts_the_stage_before_it():
    retry = Retry()
    assert [retry.fail("facts") for _ in range(RETRIES)] == ["facts"] * RETRIES
    assert retry.fail("facts") == "timeline"
    assert retry.k["facts"] == 0 and retry.k["timeline"] == 1
    assert retry.counters() == (0, 0, 1, 6, 6, 6, 6, 6)


def test_escalation_walks_back_past_a_stage_that_is_also_used_up():
    retry = Retry()
    for _ in range(RETRIES):
        retry.fail("timeline")
    for _ in range(RETRIES):
        retry.fail("facts")  # timeline keeps its five retries: only a restart before it resets them
    assert (retry.k["timeline"], retry.k["facts"]) == (RETRIES, RETRIES)
    assert retry.fail("facts") == "truth"  # facts and timeline are both used up
    assert (retry.k["facts"], retry.k["timeline"], retry.k["truth"]) == (0, 0, 1)


def test_roster_has_nowhere_to_go():
    retry = Retry()
    assert [retry.fail("roster") for _ in range(RETRIES)] == ["roster"] * RETRIES
    with pytest.raises(Exhausted):
        retry.fail("roster")


def test_the_earliest_fix_stage_is_taken_in_pipeline_order():
    assert earliest([FixStage.FACTS, FixStage.ROSTER]) == "roster"
    assert earliest([FixStage.GATING, FixStage.SKIN]) == "gating"  # skin comes after gating
    assert earliest([FixStage.PLACEMENT]) == "placement"
    assert earliest([FixStage.SKIN, FixStage.TIMELINE, FixStage.GATING]) == "timeline"


def random_failures(seed: int) -> list[str]:
    """Failures of a few stages only, so that the same stage fails again and again (and the
    controller escalates and, now and then, runs out)."""
    rng = random.Random(seed)
    stages = rng.sample(PIPELINE, rng.randint(1, 3))
    return rng.choices(stages, k=rng.randint(1, 80))


def run_controller(retry: Retry, failures: list[str]) -> tuple[list[int], bool]:
    """The stage restarted after each failure, and whether the controller ran out."""
    restarted = []
    for failing in failures:
        try:
            restarted.append(N[retry.fail(failing)])
        except Exhausted:
            return restarted, True
    return restarted, False


@pytest.mark.parametrize("seed", range(40))
def test_the_controller_matches_the_model_on_random_failures(seed):
    failures = random_failures(seed)
    expected, exhausted = retry_model.model(failures)
    retry = Retry()
    assert run_controller(retry, failures) == (expected, exhausted)
    if not exhausted:
        assert retry.counters() == retry_model.counters(expected)
        assert tuple(retry.k[s] for s in PIPELINE) == retry_model.retries(expected)


def test_the_random_failures_reach_escalation_and_exhaustion():
    runs = [retry_model.model(random_failures(seed)) for seed in range(40)]
    escalated = sum(any(r < f for r, f in zip(h, h[1:], strict=False)) for h, _ in runs)
    assert sum(exhausted for _, exhausted in runs) >= 3 and escalated >= 10


class NeverEscalates(Retry):
    def fail(self, stage: str) -> str:
        for later in PIPELINE[N[stage] :]:
            self.n[later] += 1
        return stage


def test_the_comparison_with_the_model_can_tell_a_wrong_controller():
    failures = ["facts"] * 6
    expected = retry_model.model(failures)
    assert run_controller(Retry(), failures) == expected
    assert run_controller(NeverEscalates(), failures) != expected
