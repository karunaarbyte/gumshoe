"""What a turn needs: the services, bundled so each stage takes one argument, and the
per-game conversation record that a turn reads and updates."""

from dataclasses import dataclass, field

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.game import GameClient
from gumshoe.agent.llm import Llm
from gumshoe.agent.pending import Pending
from gumshoe.decider import Decider


@dataclass(frozen=True)
class Deps:
    client: GameClient
    decider: Decider
    llm: Llm
    config: AgentConfig


@dataclass
class TurnContext:
    """Mutable: `take_turn` updates it in place, lists included, so the service (plan 4c) must
    pass the LIVE object, not a copy."""

    game: str
    pending: Pending | None = None
    exchanges: list[tuple[str, str]] = field(default_factory=list)  # every turn, for the decider
    talks: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # suspect -> dialogue
