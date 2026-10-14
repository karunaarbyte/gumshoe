"""Typed request models for the System One API (Jev / Nimble)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

# A backend's numbers are checked at the contract: a NaN, an infinity or a probability outside
# 0..1 is a DeciderParseError (a recorded failure, and the shadow is used), never a value the
# game acts on or the stats store keeps.
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    # option name -> description of when to pick it
    criteria: dict[str, str] = Field(min_length=2, max_length=26)


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    # ordered rubric, lowest level first
    criteria: list[str] = Field(min_length=2)


Question = Annotated[
    ChoiceQuestion | NoulQuestion | ScoreQuestion,
    Field(discriminator="type"),
]


class DecisionRequest(BaseModel):
    model: str
    state: str
    questions: dict[str, Question] = Field(min_length=1, max_length=64)

    @field_validator("state")
    @classmethod
    def _state_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("state must not be blank")
        return value


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: Probability  # probability of "yes"

    @property
    def yes(self) -> bool:
        return self.noul >= 0.5


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float = Field(ge=0, allow_inf_nan=False)  # probability-weighted level index (0-based)
    legend: dict[str, str]
    probabilities: dict[str, Probability]
    confidence: Probability


Answer = Annotated[
    ChoiceAnswer | NoulAnswer | ScoreAnswer,
    Field(discriminator="type"),
]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class DecisionResult(BaseModel):
    model: str
    answers: dict[str, Answer]
    usage: Usage | None = None

    def _get[A: BaseModel](self, name: str, kind: type[A]) -> A:
        answer = self.answers[name]
        if not isinstance(answer, kind):
            raise TypeError(
                f"question {name!r} has a {answer.type!r} answer, expected {kind.__name__}"
            )
        return answer

    def choice(self, name: str) -> ChoiceAnswer:
        return self._get(name, ChoiceAnswer)

    def noul(self, name: str) -> NoulAnswer:
        return self._get(name, NoulAnswer)

    def score(self, name: str) -> ScoreAnswer:
        return self._get(name, ScoreAnswer)
