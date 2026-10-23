"""What a UI reads about the server itself: health and the game's fixed numbers."""

from functools import cache
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gumshoe.cases import load_builtin_pack, supported_presets

PACK = "castle"
MAX_ATTEMPTS = 3  # the engine's (gumshoe.cases.play.state.MAX_ATTEMPTS; a test keeps them equal)


class PersonaModels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: str
    dramatic: str


class Health(BaseModel):
    """`game` is off when the game endpoints answer 503 (no Jev key, or not started); `reason`
    says why. Names and models only, never a key or a URL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"] = "ok"
    game: Literal["on", "off"]
    reason: str | None
    primary: str
    shadow: str | None
    persona_models: PersonaModels
    personas: Literal["up", "down"]  # whether the persona model server answers; down = stock lines
    mode: Literal["normal", "slow"] = "normal"  # slow: the daily Jev budget is spent, Nimble alone


class Meta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    presets: tuple[str, ...]
    default_preset: str
    max_attempts: int
    max_turn_chars: int


class ClientUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    tokens: int


class AdminUsage(BaseModel):
    """The operator's view of today's Jev spend and the server's load (`/api/admin/usage`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: str
    jev_tokens_today: int
    jev_daily_cap: int
    jev_ip_daily_cap: int
    mode: Literal["normal", "slow"]
    games_open: int
    turns_running: int
    queued: int
    shadow_skipped: int
    sessions_seen: int  # sessions issued since the server started
    saves_held: int
    top_clients: list[ClientUsage]  # the five biggest Jev spenders today


@cache
def presets() -> tuple[str, ...]:
    return supported_presets(load_builtin_pack(PACK))
