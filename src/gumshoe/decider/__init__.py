"""Typed decision client for Jev and Nimble.

Layers (imports point one way: tools -> backends -> contract):

    contract/   pure types, the Decider interface, demo samples; no I/O, no backend knowledge
    backends/   profiles, the HTTP client, and the factory that builds a Decider
    tools/      CLI, comparison, rendering; nothing else depends on it

Rules (enforced by tests/test_architecture.py):
  * contract/ never imports backends/, tools/, or httpx.
  * backends/ never imports tools/.
  * Only __main__.py (the entrypoint) imports tools/ from outside tools/.
  * Code outside this package imports from `gumshoe.decider` only, never its submodules.

A new file goes in the layer matching what it knows about. If it fits none, add a layer.
"""

from gumshoe.decider.backends.factory import make_decider
from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import (
    DeciderAPIError,
    DeciderConfigError,
    DeciderConnectionError,
    DeciderError,
    DeciderParseError,
)
from gumshoe.decider.contract.models import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    DecisionResult,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    Usage,
)

__all__ = [
    "Answer",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "Decider",
    "DeciderAPIError",
    "DeciderConfigError",
    "DeciderConnectionError",
    "DeciderError",
    "DeciderParseError",
    "DecisionRequest",
    "DecisionResult",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "ScoreAnswer",
    "ScoreQuestion",
    "Usage",
    "make_decider",
]
