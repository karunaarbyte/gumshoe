import json
import os
from pathlib import Path

import pytest
from pydantic import AliasChoices

from gumshoe.config import Settings

FIXTURES = Path(__file__).parent.parent / "fixtures"


def settings_env_vars() -> set[str]:
    """Every environment variable Settings reads: field names and their aliases (such as
    GUMSHOE_SAVES for saves_dir), upper-cased; they are matched case-insensitively."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice).upper() for choice in alias.choices)
        elif isinstance(alias, str):
            names.add(alias.upper())
    return names


SETTINGS_ENV_VARS = settings_env_vars()


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """Tests must not depend on the developer's shell: drop every Settings variable, any case."""
    for name in list(os.environ):
        if name.upper() in SETTINGS_ENV_VARS:
            monkeypatch.delenv(name)


@pytest.fixture
def load_fixture():
    def _load(name: str):
        return json.loads((FIXTURES / name).read_text())

    return _load
