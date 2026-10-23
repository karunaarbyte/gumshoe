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

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails
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


_SECRET_FIELDS = ("jev_api_key", "session_secret", "admin_token")


class Settings(BaseSettings):
    # hide_input_in_errors: a validation error must never echo a raw secret from the environment.
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

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
    # The built UI, served at `/` when its index.html exists (`npm run build` in frontend/).
    ui_dist: Path = Path("frontend/dist")

    # Prices in US dollars per million tokens, for the cost columns of the stats (0 = free).
    jev_usd_per_mtok_in: float = Field(0.0, ge=0, allow_inf_nan=False)
    jev_usd_per_mtok_out: float = Field(0.0, ge=0, allow_inf_nan=False)
    nimble_usd_per_mtok_in: float = Field(0.0, ge=0, allow_inf_nan=False)
    nimble_usd_per_mtok_out: float = Field(0.0, ge=0, allow_inf_nan=False)

    # Jev spend caps per UTC day, in input tokens (0 = no cap). Over a cap, Nimble alone decides.
    jev_daily_tokens: int = Field(5_000_000, ge=0)
    jev_ip_daily_tokens: int = Field(300_000, ge=0)

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
    # Admin access to the stats and decisions (32+ characters; empty = those endpoints are off).
    admin_token: SecretStr = SecretStr("")
    decision_retention_days: int = Field(30, ge=0)  # older decisions are deleted; 0 = keep forever
    # /docs, /redoc and /openapi.json, for local use only (refused with PUBLIC_ORIGIN). The strict
    # CSP stops the /docs and /redoc pages loading their scripts from a CDN; /openapi.json works.
    api_docs: bool = False

    # Limits (0 = unlimited). Per session, per client IP, and global.
    session_games_open: int = Field(3, ge=0)
    session_games_per_hour: int = Field(20, ge=0)
    session_turns_per_minute: int = Field(30, ge=0)
    session_turns_in_flight: int = Field(1, ge=0)  # turns running at once across a session's games
    ip_new_sessions_per_hour: int = Field(10, ge=0)
    ip_requests_per_minute: int = Field(300, ge=0)
    ip_turns_per_minute: int = Field(60, ge=0)
    ip_turns_in_flight: int = Field(2, ge=0)
    ip_games_open: int = Field(6, ge=0)
    max_games: int | None = Field(None, ge=1)  # None: 1000 locally, 200 in public mode
    max_parallel_turns: int = Field(2, ge=0)  # turns processed at once (the Ollama bottleneck)
    turn_queue_size: int = Field(4, ge=0)
    turn_queue_wait_s: float = Field(20.0, gt=0, allow_inf_nan=False)
    shadow_parallel: int = Field(1, ge=0)  # background Nimble shadow calls at once
    limiter_max_keys: int = Field(20000, ge=100)
    game_idle_minutes: int = Field(30, ge=0)  # an idle game is closed; 0 = never
    save_retention_days: int = Field(30, ge=0)  # older saves are deleted; 0 = keep
    session_saves: int = Field(10, ge=0)  # saves per session; 0 = unlimited
    ip_saves: int = Field(20, ge=0)  # saves per client IP; 0 = unlimited
    # Behind exactly one trusted proxy (the tunnel): read the client from X-Forwarded-For.
    trust_proxy: bool = False

    @field_validator("decider_shadow", mode="before")
    @classmethod
    def _blank_shadow_means_off(cls, value: Any) -> Any:
        return None if value == "" else value

    @field_validator("saves_dir", mode="before")
    @classmethod
    def _blank_saves_means_default(cls, value: Any) -> Any:
        return "saves" if value == "" else value

    @field_validator("stats_db_path", "saves_dir", "ui_dist", mode="after")
    @classmethod
    def _resolve_against_the_project_root(cls, value: Path) -> Path:
        return _under_root(value)

    def __init__(self, **values: Any) -> None:
        # Pydantic reports the raw input of a failed check, even with hide_input_in_errors. A
        # SecretStr input is reported masked, so wrap the raw strings before anything validates.
        for name in _SECRET_FIELDS:
            if isinstance(values.get(name), str):
                values[name] = SecretStr(values[name])
        super().__init__(**values)
        self._settle_decider_roles()

    @model_validator(mode="before")
    @classmethod
    def _wrap_env_secrets(cls, data: Any) -> Any:
        # The same for values that come from the environment or .env (they are merged in after
        # __init__ runs).
        if isinstance(data, dict):
            data = {
                key: SecretStr(val) if key in _SECRET_FIELDS and isinstance(val, str) else val
                for key, val in data.items()
            }
        return data

    @field_validator("admin_token", mode="after")
    @classmethod
    def _admin_token_is_long(cls, value: SecretStr) -> SecretStr:
        # The message never includes the value. Padding (a trailing newline from an env file)
        # is rejected, not stripped, so the token a person types is the token that is checked.
        token = value.get_secret_value()
        if token != token.strip():
            raise ValueError("ADMIN_TOKEN must not start or end with whitespace")
        if token and len(token) < 32:
            raise ValueError(
                "ADMIN_TOKEN must be at least 32 characters (or empty to turn admin off)"
            )
        return value

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

    @field_validator("session_secret", mode="after")
    @classmethod
    def _public_mode_needs_a_secret(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        # A field check, not a model check: a model-level error reports the raw input dict.
        if info.data.get("public_origin") and len(value.get_secret_value()) < 32:
            raise ValueError(
                "SESSION_SECRET must be at least 32 characters when PUBLIC_ORIGIN is set"
            )
        return value

    @field_validator("api_docs", mode="after")
    @classmethod
    def _no_docs_in_public_mode(cls, value: bool, info: ValidationInfo) -> bool:
        if value and info.data.get("public_origin"):
            raise ValueError("API_DOCS must be off when PUBLIC_ORIGIN is set")
        return value

    def _settle_decider_roles(self) -> None:
        # Not a model_validator: a model-level error reports the raw input dict, which holds
        # plain-str secrets from the environment. Errors raised here carry no input.
        try:
            self._roles_must_differ()
        except ValueError as exc:
            raise ValidationError.from_exception_data(
                type(self).__name__,
                [InitErrorDetails(type="value_error", loc=(), input=None, ctx={"error": exc})],
            ) from None

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
    def admin_enabled(self) -> bool:
        return bool(self.admin_token.get_secret_value())

    @property
    def public_mode(self) -> bool:
        return bool(self.public_origin)

    @property
    def effective_max_games(self) -> int:
        if self.max_games is not None:
            return self.max_games
        return 200 if self.public_mode else 1000

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """The CORS origins as a tuple, blanks dropped (empty: no cross-origin access)."""
        return tuple(item.strip() for item in self.cors_origins.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
