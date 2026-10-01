import time

import pytest

from gumshoe.decider.contract.errors import DeciderConnectionError
from gumshoe.decider.contract.models import ChoiceAnswer, DecisionResult
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.decider.tools.compare import Outcome, compare_backends, run_one
from gumshoe.decider.tools.render import format_comparison, format_result, summarise
from tests.decider.fakes import FakeDecider


@pytest.fixture
def result(load_fixture):
    return DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))


async def test_run_one_success_measures_latency(result):
    outcome = await run_one(FakeDecider("a", result=result, delay=0.05), DEMO_STATE, DEMO_QUESTIONS)
    assert outcome.result is result
    assert outcome.error is None
    assert outcome.latency_ms is not None
    assert outcome.latency_ms >= 40


async def test_run_one_captures_decider_errors():
    err = DeciderConnectionError("b", "cannot reach")
    outcome = await run_one(FakeDecider("b", error=err), DEMO_STATE, DEMO_QUESTIONS)
    assert outcome.result is None
    assert outcome.error is not None
    assert "cannot reach" in outcome.error


async def test_run_one_passes_the_node_label(result):
    fake = FakeDecider("a", result=result)
    await run_one(fake, DEMO_STATE, DEMO_QUESTIONS, node="intent")
    assert fake.nodes == ["intent"]


async def test_compare_runs_backends_concurrently(result):
    deciders = {
        "a": FakeDecider("a", result=result, delay=0.2),
        "b": FakeDecider("b", result=result, delay=0.2),
    }
    started = time.perf_counter()
    outcomes = await compare_backends(deciders, DEMO_STATE, DEMO_QUESTIONS)
    elapsed = time.perf_counter() - started
    assert list(outcomes) == ["a", "b"]
    assert elapsed < 0.35  # sequential would be >= 0.4


async def test_one_failure_does_not_hide_the_other(result):
    deciders = {
        "ok": FakeDecider("ok", result=result),
        "bad": FakeDecider("bad", error=DeciderConnectionError("bad", "down")),
    }
    outcomes = await compare_backends(deciders, DEMO_STATE, DEMO_QUESTIONS)
    assert outcomes["ok"].result is not None
    assert outcomes["bad"].error is not None
    assert "down" in outcomes["bad"].error


def test_summarise_each_answer_type(result):
    assert summarise(result.answers["intent"]).startswith("dialogue ")
    assert summarise(result.answers["needs_interrogation"]).startswith("yes ")
    assert summarise(result.answers["urgency"]).replace(".", "").isdigit()


def test_format_result_lists_every_question(result):
    text = format_result(result)
    for name in ("intent", "needs_interrogation", "urgency"):
        assert name in text
    assert "nimble" in text  # model name header


def test_comparison_marks_agreement_and_disagreement(result):
    other = result.model_copy(deep=True)
    other.answers["intent"] = ChoiceAnswer(
        type="choice",
        choice="action",
        probabilities={"action": 0.9, "dialogue": 0.1},
        confidence=0.8,
    )
    text = format_comparison(
        {
            "nimble": Outcome(result=result, latency_ms=120.0),
            "jev": Outcome(result=other, latency_ms=300.0),
        }
    )
    lines = {line.split()[0]: line for line in text.splitlines() if line.strip()}
    assert lines["intent"].rstrip().endswith("NO")
    assert lines["needs_interrogation"].rstrip().endswith("yes")
    assert lines["urgency"].rstrip().endswith("yes")  # identical scores
    assert "120" in lines["latency_ms"] and "300" in lines["latency_ms"]


def test_comparison_shows_errors_and_placeholders(result):
    text = format_comparison(
        {
            "nimble": Outcome(result=result, latency_ms=100.0),
            "jev": Outcome(error="[jev] JEV_API_KEY is not set"),
        }
    )
    assert "jev error: [jev] JEV_API_KEY is not set" in text
    assert "-" in text
