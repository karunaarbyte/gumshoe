"""Typed request models for the System One API (Jev / Nimble)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


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
