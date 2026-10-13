"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Backend = Literal["jev", "nimble"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The backend the game trusts, and an optional one that runs alongside it.
    decider_primary: Backend = "jev"
    decider_shadow: Backend | None = "nimble"

    jev_base_url: str = "https://api.typesafe.ai/v1"
    jev_api_key: SecretStr = SecretStr("")
    jev_model: str = "jev-latest"

    nimble_base_url: str = "http://localhost:11434/v1"
    nimble_model: str = "nimble"

    request_timeout_s: float = Field(30.0, gt=0, allow_inf_nan=False)

    stats_db_path: Path = Path("data/decisions.db")
    # A backend with no call in this many seconds counts as cold (e.g. Ollama unloaded the model).
    cold_after_s: float = Field(300.0, gt=0, allow_inf_nan=False)

    # The agent loop (spec 2026-10-12-agent-loop-4-design.md, section 9).
    ollama_base_url: str = "http://localhost:11434/v1"
    persona_model_default: str = "ministral-3:14b"
    persona_model_dramatic: str = "gemma4:12b"
    dramatic_from: float = Field(2.5, ge=0, le=4, allow_inf_nan=False)
    confidence_gate: float = Field(0.6, gt=0, le=1, allow_inf_nan=False)
    # yes needs >= confirm_gate and no needs <= 1 - confirm_gate, so it must exceed 0.5
    confirm_gate: float = Field(0.8, gt=0.5, le=1, allow_inf_nan=False)
    max_redrafts: int = Field(3, ge=0, le=10)
    llm_timeout_s: float = Field(60.0, gt=0, allow_inf_nan=False)

    @field_validator("decider_shadow", mode="before")
    @classmethod
    def _blank_shadow_means_off(cls, value: Any) -> Any:
        return None if value == "" else value

    @model_validator(mode="after")
    def _roles_must_differ(self) -> Self:
        if self.decider_shadow == self.decider_primary:
            raise ValueError(
                "DECIDER_SHADOW must differ from DECIDER_PRIMARY "
                "(leave it blank to disable shadowing)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
