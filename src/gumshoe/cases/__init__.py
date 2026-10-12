"""The case engine: immutable detective cases and a deterministic validator.

Layers (imports point one way): core < model < rules < {validate, play, packs}
< generate < simulate < tools. Code outside this package (the MCP server included) imports only
the names below; tests/test_architecture.py enforces the rules.
"""

from gumshoe.cases.generate.api import CaseGenerationError
from gumshoe.cases.generate.api import generate as generate_case
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import dump_case, load_case, skeleton_digest, skin_hash
from gumshoe.cases.model.spec import UnsupportedPreset, supported_presets
from gumshoe.cases.play import (
    AccusationPlan,
    AccusationResult,
    AxisOptions,
    GameNotOver,
    GameOver,
    GameSession,
    HandleCollision,
    NotebookView,
    ParsedAccusation,
    PersonaBrief,
    PlayerCaseView,
    ReplyCheck,
    RevealView,
    SourceResult,
    StateMismatch,
    UnknownHandle,
    View,
    load_session,
)
from gumshoe.cases.tools.builtin import BuiltinPackError, load_builtin_pack
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Issue, Profile, Report, Severity
from gumshoe.cases.validate.runner import validate as validate_case

__all__ = [
    "CATALOGUE",
    "AccusationPlan",
    "AccusationResult",
    "AxisOptions",
    "BuiltinPackError",
    "Case",
    "CaseGenerationError",
    "GameNotOver",
    "GameOver",
    "GameSession",
    "HandleCollision",
    "Issue",
    "NotebookView",
    "Pack",
    "ParsedAccusation",
    "PersonaBrief",
    "PlayerCaseView",
    "Profile",
    "ReplyCheck",
    "Report",
    "RevealView",
    "Severity",
    "SourceResult",
    "StateMismatch",
    "UnknownHandle",
    "UnsupportedPreset",
    "View",
    "dump_case",
    "generate_case",
    "load_builtin_pack",
    "load_case",
    "load_session",
    "skeleton_digest",
    "skin_hash",
    "supported_presets",
    "validate_case",
]
