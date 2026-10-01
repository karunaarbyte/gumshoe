"""Typed decision client for Jev and Nimble.

Layers (imports point one way: tools -> backends -> shadow -> contract):

    contract/   pure types, the Decider interface, demo samples; no I/O, no backend knowledge
    shadow/     ShadowDecider (primary + shadow, fallback) and the Recorder interface
    backends/   profiles, the HTTP client, and the factory that builds a Decider
    tools/      CLI, comparison, rendering; nothing else depends on it

Rules (enforced by tests/test_architecture.py):
  * contract/ never imports shadow/, backends/, tools/, or httpx.
  * shadow/ imports only contract/ (and the standard library).
  * backends/ never imports tools/.
  * This package never imports gumshoe.stats or gumshoe.api (they depend on it, not the reverse).
  * Only __main__.py (the entrypoint) imports tools/ from outside tools/.
  * Code outside this package imports from `gumshoe.decider` only, never its submodules.

A new file goes in the layer matching what it knows about. If it fits none, add a layer.
"""

from gumshoe.decider.backends.factory import make_decider
from gumshoe.decider.contract.agreement import answers_agree
from gumshoe.decider.contract.answers import answer_confidence, answer_verdict
from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import (
    DeciderAllFailedError,
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
from gumshoe.decider.contract.samples import DEMO_PLAYER_INPUTS, DEMO_QUESTIONS
from gumshoe.decider.shadow.records import CallRecord, Recorder
from gumshoe.decider.shadow.shadow import ShadowDecider

__all__ = [
    "DEMO_PLAYER_INPUTS",
    "DEMO_QUESTIONS",
    "Answer",
    "CallRecord",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "Decider",
    "DeciderAPIError",
    "DeciderAllFailedError",
    "DeciderConfigError",
    "DeciderConnectionError",
    "DeciderError",
    "DeciderParseError",
    "DecisionRequest",
    "DecisionResult",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "Recorder",
    "ScoreAnswer",
    "ScoreQuestion",
    "ShadowDecider",
    "Usage",
    "answer_confidence",
    "answer_verdict",
    "answers_agree",
    "make_decider",
]
