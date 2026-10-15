import pytest

from gumshoe.decider.contract.errors import DeciderConnectionError
from gumshoe.decider.contract.models import DecisionResult
from gumshoe.decider.shadow.records import PREVIEW_CHARS, CallOutcome, build_record


@pytest.fixture
def result(load_fixture):
    return DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))


def outcome(**overrides):
    base = {
        "backend": "nimble",
        "role": "shadow",
        "ts": "2026-10-01T10:00:00.000000+00:00",
        "cold": False,
        "latency_ms": 640.5,
    }
    return CallOutcome(**{**base, **overrides})


def test_successful_call_is_summarised(result):
    record = build_record(
        decision_id="d1",
        node="intent",
        state="hello",
        call=outcome(result=result),
        used=False,
        fallback=False,
    )
    assert (record.decision_id, record.node, record.backend, record.role) == (
        "d1",
        "intent",
        "nimble",
        "shadow",
    )
    assert record.used is False and record.fallback is False and record.cold is False
    assert record.latency_ms == 640.5
    assert (record.input_tokens, record.output_tokens) == (1000, 4)
    # confidences in the fixture: choice 0.9397, noul max(0.9977, 0.0023), score 0.3963
    assert record.mean_confidence == pytest.approx((0.93969 + 0.99766 + 0.39633) / 3, abs=1e-3)
    assert record.min_confidence == pytest.approx(0.39633, abs=1e-3)
    assert record.error is None
    assert record.answers is not None
    assert set(record.answers) == {"intent", "needs_interrogation", "urgency"}


def test_failed_call_has_no_numbers_but_keeps_the_error():
    failure = DeciderConnectionError("jev", "cannot reach")
    record = build_record(
        decision_id="d1",
        node="intent",
        state="hello",
        call=outcome(backend="jev", role="primary", failure=failure),
        used=False,
        fallback=True,
    )
    assert record.error == "DeciderConnectionError (jev)"
    assert record.answers is None
    assert record.input_tokens is None and record.output_tokens is None
    assert record.mean_confidence is None and record.min_confidence is None
    assert record.fallback is True


def test_state_is_truncated_to_a_preview(result):
    record = build_record(
        decision_id="d",
        node="n",
        state="é" * 5000,
        call=outcome(result=result),
        used=True,
        fallback=False,
    )
    assert len(record.state_preview) == PREVIEW_CHARS


def test_result_without_usage_is_fine(result):
    result = result.model_copy(update={"usage": None})
    record = build_record(
        decision_id="d", node="n", state="s", call=outcome(result=result), used=True, fallback=False
    )
    assert record.input_tokens is None and record.output_tokens is None
