"""The agent loop: free text in, game actions and in-character replies out.

Imports point one way (enforced by tests/test_architecture.py): only this package, the top level
of gumshoe.cases and gumshoe.decider, the stdlib and pydantic; the `mcp` SDK only in game.py and
httpx only in llm.py. It never imports gumshoe.mcp_server: it talks to the game through the MCP
client it is given.
"""

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.deps import Deps, TurnContext
from gumshoe.agent.events import EVENT_ADAPTER, TurnEvent
from gumshoe.agent.game import GameClient, NewGameView, SaveView, ToolFailure
from gumshoe.agent.llm import Llm, LlmError, LlmMessage, OllamaLlm
from gumshoe.agent.pending import Pending
from gumshoe.agent.turn import take_confirm, take_turn

__all__ = [
    "EVENT_ADAPTER", "AgentConfig", "Deps", "GameClient", "Llm", "LlmError", "LlmMessage",
    "NewGameView", "OllamaLlm", "Pending", "SaveView", "ToolFailure", "TurnContext", "TurnEvent",
    "take_confirm", "take_turn",
]  # fmt: skip
