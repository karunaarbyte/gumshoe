"""The case engine: immutable detective cases and a deterministic validator.

Layers (imports point one way): core < model < rules < {validate, play, packs}
< generate < simulate < tools. Code outside this package (the MCP server included) imports only
the names below; tests/test_architecture.py enforces the rules.
"""

from gumshoe.cases.generate.api import CaseGenerationError, VersionMismatch
from gumshoe.cases.generate.api import generate as generate_case
from gumshoe.cases.generate.api import regenerate as regenerate_case
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import dump_case, load_case, skeleton_digest, skin_hash
from gumshoe.cases.model.spec import UnsupportedPreset, supported_presets
from gumshoe.cases.play import (
    AccusationPlan,
    AccusationQuestions,
    AccusationResult,
    AxisOptions,
    BadAnswers,
    GameNotOver,
    GameOver,
    GameSession,
    HandleCollision,
    InconsistentState,
    LocationView,
    NoAccusationPrompt,
    NotebookFact,
    NotebookView,
    ParsedAccusation,
    PersonaBrief,
    PlayerCaseView,
    QuestionView,
    ReplyCheck,
    RevealView,
    SourceResult,
    StateMismatch,
    SuspectView,
    UnknownHandle,
    View,
    load_session,
)
from gumshoe.cases.tools.builtin import BuiltinPackError, load_builtin_pack
from gumshoe.cases.tools.registry import (
    DEFAULT_PACK,
    PackInfo,
    bundled_pack,
    bundled_packs,
    pack_info,
)
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Issue, Profile, Report, Severity
from gumshoe.cases.validate.runner import validate as validate_case

__all__ = [
    "CATALOGUE",
    "DEFAULT_PACK",
    "AccusationPlan",
    "AccusationQuestions",
    "AccusationResult",
    "AxisOptions",
    "BadAnswers",
    "BuiltinPackError",
    "Case",
    "CaseGenerationError",
    "GameNotOver",
    "GameOver",
    "GameSession",
    "HandleCollision",
    "InconsistentState",
    "Issue",
    "LocationView",
    "NoAccusationPrompt",
    "NotebookFact",
    "NotebookView",
    "Pack",
    "PackInfo",
    "ParsedAccusation",
    "PersonaBrief",
    "PlayerCaseView",
    "Profile",
    "QuestionView",
    "ReplyCheck",
    "Report",
    "RevealView",
    "Severity",
    "SourceResult",
    "StateMismatch",
    "SuspectView",
    "UnknownHandle",
    "UnsupportedPreset",
    "VersionMismatch",
    "View",
    "bundled_pack",
    "bundled_packs",
    "dump_case",
    "generate_case",
    "load_builtin_pack",
    "load_case",
    "load_session",
    "pack_info",
    "regenerate_case",
    "skeleton_digest",
    "skin_hash",
    "supported_presets",
    "validate_case",
]
