"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
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

    @field_validator("decider_shadow", mode="before")
    @classmethod
    def _blank_shadow_means_off(cls, value: Any) -> Any:
        return None if value == "" else value

    @model_validator(mode="after")
    def _roles_must_differ(self) -> Self:
        if self.decider_shadow == self.decider_primary:
            raise ValueError(
                "DECIDER_SHADOW must differ from DECIDER_PRIMARY (leave it blank to disable shadowing)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
