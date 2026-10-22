"""Application settings, loaded from environment variables and the project's `.env`.

Paths: `.env` is read from the project root (the folder holding `pyproject.toml`), never from the
working directory, and a relative `STATS_DB_PATH` or `SAVES_DIR` is resolved against that root.
So the app finds its key, its stats database and its saves wherever it is started from. An
absolute path is used as given.

Unknown keys in `.env` or the environment are ignored on purpose (`extra="ignore"`): the file is
shared with other tools. The flip side is that a misspelled variable is silently ignored too, so
check the spelling against `.env.example`.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

Backend = Literal["jev", "nimble"]

# src/gumshoe/config.py -> the repository root (run from a source checkout, as `uv run` does)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _under_root(path: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _origin(text: str) -> str:
    """One CORS origin: scheme://host[:port], nothing else (and never a wildcard)."""
    parts = urlsplit(text)
    if (
        "*" in text
        or parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            f"CORS_ORIGINS entry {text!r} must be an explicit origin like http://localhost:5173 "
            "(no path, no trailing slash, no wildcard)"
        )
    return text


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # The backend the game trusts, and an optional one that runs alongside it. When the primary
    # is nimble and DECIDER_SHADOW is not set at all, shadowing is off (not nimble twice).
    decider_primary: Backend = "jev"
    decider_shadow: Backend | None = "nimble"
    # One switch for the common case. On (default): the roles above apply (Jev decides, Nimble
    # shadows it). Off: Nimble alone decides, with no Jev call and no Jev key needed, whatever
    # the two settings above say.
    shadow_run: bool = True

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

    # Saves (SAVES_DIR; the older GUMSHOE_SAVES still works, SAVES_DIR wins when both are set).
    saves_dir: Path = Field(
        Path("saves"), validation_alias=AliasChoices("saves_dir", "gumshoe_saves")
    )

    # Prices in US dollars per million tokens, for the cost columns of the stats (0 = free).
    jev_usd_per_mtok_in: float = Field(0.0, ge=0, allow_inf_nan=False)
    jev_usd_per_mtok_out: float = Field(0.0, ge=0, allow_inf_nan=False)
    nimble_usd_per_mtok_in: float = Field(0.0, ge=0, allow_inf_nan=False)
    nimble_usd_per_mtok_out: float = Field(0.0, ge=0, allow_inf_nan=False)

    # The HTTP API: comma-separated browser origins allowed by CORS (empty = none, never "*").
    cors_origins: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = Field(8000, ge=1, le=65535)
    turn_timeout_s: float = Field(120.0, gt=0, allow_inf_nan=False)
    max_body_bytes: int = Field(16384, ge=1024)
    # Public mode. PUBLIC_ORIGIN is the site's own https origin; setting it turns on the
    # Secure `__Host-` cookie, the strict Origin check and the startup checks. SESSION_SECRET
    # signs the session cookie and keys the save owners (32+ characters in public mode).
    public_origin: str = ""
    session_secret: SecretStr = SecretStr("")

    @field_validator("decider_shadow", mode="before")
    @classmethod
    def _blank_shadow_means_off(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("saves_dir", mode="before")
    @classmethod
    def _blank_saves_means_default(cls, value: Any) -> Any:
        return "saves" if value == "" else value

    @field_validator("stats_db_path", "saves_dir", mode="after")
    @classmethod
    def _resolve_against_the_project_root(cls, value: Path) -> Path:
        return _under_root(value)

    @field_validator("jev_base_url", mode="after")
    @classmethod
    def _jev_needs_https(cls, value: str) -> str:
        """The Jev key travels in a header, so plain http is allowed only to this machine."""
        parts = urlsplit(value)
        local = parts.scheme == "http" and parts.hostname in LOCAL_HOSTS
        if not parts.hostname or not (parts.scheme == "https" or local):
            raise ValueError("JEV_BASE_URL must be an https URL (http only for localhost)")
        return value

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _explicit_origins(cls, value: str) -> str:
        for item in value.split(","):
            if item.strip():
                _origin(item.strip())
        return value

    @field_validator("public_origin", mode="after")
    @classmethod
    def _public_origin_is_an_https_origin(cls, value: str) -> str:
        if not value:
            return value
        try:
            origin = _origin(value)
        except ValueError as exc:
            raise ValueError(f"PUBLIC_ORIGIN: {exc}") from exc
        if urlsplit(origin).username is not None:
            raise ValueError("PUBLIC_ORIGIN must not contain a username or password")
        if urlsplit(origin).scheme != "https":
            raise ValueError(
                "PUBLIC_ORIGIN must be an https origin like https://gumshoe.example.com"
            )
        return origin

    @model_validator(mode="after")
    def _public_mode_needs_a_secret(self) -> Self:
        if self.public_origin and len(self.session_secret.get_secret_value()) < 32:
            raise ValueError(
                "SESSION_SECRET must be at least 32 characters when PUBLIC_ORIGIN is set"
            )
        return self

    @model_validator(mode="after")
    def _roles_must_differ(self) -> Self:
        if not self.shadow_run:
            said = {"decider_primary", "decider_shadow"} & self.model_fields_set
            if (self.decider_primary, self.decider_shadow) != ("nimble", None) and said:
                logger.warning(
                    "SHADOW_RUN=false overrides DECIDER_PRIMARY and DECIDER_SHADOW: "
                    "Nimble alone decides"
                )
            self.decider_primary, self.decider_shadow = "nimble", None
            return self
        if self.decider_shadow == self.decider_primary:
            if "decider_shadow" not in self.model_fields_set:
                self.decider_shadow = None  # the default shadow would just repeat the primary
                return self
            raise ValueError(
                "DECIDER_SHADOW must differ from DECIDER_PRIMARY "
                "(leave it blank to disable shadowing)"
            )
        return self

    @property
    def public_mode(self) -> bool:
        return bool(self.public_origin)

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """The CORS origins as a tuple, blanks dropped (empty: no cross-origin access)."""
        return tuple(item.strip() for item in self.cors_origins.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
