"""Tunables for the agent loop. Plan 4c maps the application settings onto this."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    confidence_gate: float = 0.6  # below this an intent or target is not trusted
    confirm_gate: float = 0.8  # yes needs >= this, no needs <= 1 - this
    max_redrafts: int = 3
    dramatic_from: float = 2.5  # weight score (0-4 scale) from which the dramatic model is used
    model_default: str = "ministral-3:14b"
    model_dramatic: str = "gemma4:12b"
    max_text: int = 4000  # check_reply refuses longer texts; drafts are truncated to this
    notebook_cap: int = 30  # recent facts sent to the decider (plus every contradicted fact)
    exchanges_kept: int = (
        2  # past exchanges sent to the decider; also the length of a suspect's persona history
    )

    def __post_init__(self) -> None:
        if not 0 < self.confidence_gate <= 1:
            raise ValueError("confidence_gate must be in (0, 1]")
        if not 0.5 < self.confirm_gate <= 1:
            raise ValueError("confirm_gate must be in (0.5, 1] so the yes and no bands cannot meet")
        if self.max_redrafts < 0:
            raise ValueError("max_redrafts must not be negative")
        if self.max_text < 1 or self.notebook_cap < 1 or self.exchanges_kept < 0:
            raise ValueError("max_text and notebook_cap must be positive, exchanges_kept >= 0")
