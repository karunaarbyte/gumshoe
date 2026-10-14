import pytest
from pydantic import ValidationError

from gumshoe.agent.events import (
    EVENT_ADAPTER,
    Cancelled,
    Clarify,
    Confirm,
    Done,
    GameOver,
    IntentEvent,
    PostCheck,
    Reply,
    ToolCall,
    ToolResult,
    TurnEvent,
)
from gumshoe.cases import RevealView

EVENTS: list[TurnEvent] = [
    IntentEvent(decision_id="d1", intent="search", target="h_x", confidence=0.9),
    Clarify(reason="low_confidence", text="Which place?"),
    ToolCall(tool="search", args={"game": "g", "location": "h_x"}),
    ToolResult(tool="search", ok=True, data={"status": "ok"}),
    ToolResult(tool="search", ok=False, code="game_over", message="the game has ended"),
    Reply(speaker="Berta the cook", text="I was in the kitchen.", source="draft"),
    PostCheck(
        decision_id="d2", contradicts_says=0.1, claims_guilt_or_blames_other=0.2, failed=False
    ),
    PostCheck(
        decision_id="d3", contradicts_says=None, claims_guilt_or_blames_other=None, failed=True
    ),
    Confirm(
        pending="accuse",
        pending_id="p1",
        text="Your accusation: A / B / C. Confirm?",
        warnings=("w",),
    ),
    Cancelled(),
    GameOver(outcome="won", reveal=RevealView(culprit="A", method="m", motive="v", secret="s")),
    Done(),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: e.kind)
def test_every_event_round_trips_through_the_discriminated_union(event):
    data = event.model_dump(mode="json")
    assert data["kind"] == event.kind
    assert EVENT_ADAPTER.validate_python(data) == event


def test_events_are_frozen_and_reject_unknown_fields():
    with pytest.raises(ValidationError):
        Clarify(reason="error", text="x", extra_field=1)  # type: ignore[call-arg]
    event = Done()
    with pytest.raises(ValidationError):
        event.kind = "other"  # type: ignore[misc, assignment]


def test_an_unknown_reason_or_source_is_refused():
    with pytest.raises(ValidationError):
        Clarify(reason="whatever", text="x")
    with pytest.raises(ValidationError):
        Reply(speaker=None, text="x", source="telepathy")


def test_all_twelve_shapes_are_in_the_union():
    assert {e.kind for e in EVENTS} == {
        "intent",
        "clarify",
        "tool_call",
        "tool_result",
        "reply",
        "post_check",
        "confirm",
        "cancelled",
        "game_over",
        "done",
    }
