"""The case engine: immutable detective cases and a deterministic validator.

Layers (imports point one way): core < model < rules < {validate, play, packs}
< generate < simulate < tools. Code outside this package imports only the names below;
tests/test_architecture.py enforces the rules.
"""

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import dump_case, load_case, skeleton_digest, skin_hash
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Issue, Profile, Report, Severity
from gumshoe.cases.validate.runner import validate as validate_case

__all__ = [
    "CATALOGUE",
    "Case",
    "Issue",
    "Pack",
    "Profile",
    "Report",
    "Severity",
    "dump_case",
    "load_case",
    "skeleton_digest",
    "skin_hash",
    "validate_case",
]
