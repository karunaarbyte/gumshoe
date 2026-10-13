"""What a turn yields. Frozen, typed and serialisable; the API streams these as SSE."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from gumshoe.cases import RevealView


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IntentEvent(_Event):
    kind: Literal["intent"] = "intent"
    decision_id: str
    intent: str
    target: str | None
    confidence: float


class Clarify(_Event):
    kind: Literal["clarify"] = "clarify"
    reason: Literal["low_confidence", "bad_target", "mismatch", "accusation", "pending", "error"]
    text: str
    decision_id: str | None = None  # the parse_accusation decision, on accusation clarifies


class ToolCall(_Event):
    kind: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]


class ToolResult(_Event):
    kind: Literal["tool_result"] = "tool_result"
    tool: str
    ok: bool
    code: str | None = None
    message: str | None = None
    data: dict[str, Any] | None = None


class Reply(_Event):
    kind: Literal["reply"] = "reply"
    speaker: str | None
    text: str
    source: Literal["draft", "canned", "help", "unreachable"]
    degraded: bool = False
    check_ok: bool = True
    violations: tuple[str, ...] = ()  # check_reply categories only


class PostCheck(_Event):
    kind: Literal["post_check"] = "post_check"
    decision_id: str
    contradicts_says: float | None
    claims_guilt_or_blames_other: float | None
    failed: bool


class Confirm(_Event):
    kind: Literal["confirm"] = "confirm"
    pending: Literal["accuse", "give_up"]
    text: str
    warnings: tuple[str, ...] = ()
    decision_id: str | None = None  # the parse_accusation decision (accuse only)


class Cancelled(_Event):
    kind: Literal["cancelled"] = "cancelled"


class GameOver(_Event):
    kind: Literal["game_over"] = "game_over"
    outcome: Literal["won", "lost", "gave_up"]
    reveal: RevealView


class Done(_Event):
    kind: Literal["done"] = "done"


TurnEvent = Annotated[
    IntentEvent
    | Clarify
    | ToolCall
    | ToolResult
    | Reply
    | PostCheck
    | Confirm
    | Cancelled
    | GameOver
    | Done,
    Field(discriminator="kind"),
]
EVENT_ADAPTER: TypeAdapter[TurnEvent] = TypeAdapter(TurnEvent)
