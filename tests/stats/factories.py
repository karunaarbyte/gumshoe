from typing import Any

from gumshoe.decider import CallRecord, ChoiceAnswer, NoulAnswer


def choice(option: str, confidence: float = 0.9) -> ChoiceAnswer:
    return ChoiceAnswer(
        type="choice", choice=option, probabilities={option: 1.0}, confidence=confidence
    )


def noul(p: float) -> NoulAnswer:
    return NoulAnswer(type="noul", noul=p)


def make_record(**overrides: Any) -> CallRecord:
    base: dict[str, Any] = {
        "decision_id": "d1",
        "node": "intent",
        "backend": "jev",
        "role": "primary",
        "used": True,
        "fallback": False,
        "cold": False,
        "ts": "2026-10-01T10:00:00.000000+00:00",
        "latency_ms": 500.0,
        "input_tokens": 400,
        "output_tokens": 80,
        "mean_confidence": 0.9,
        "min_confidence": 0.8,
        "error": None,
        "state_preview": "hello",
        "answers": {"intent": choice("dialogue")},
    }
    return CallRecord(**{**base, **overrides})
