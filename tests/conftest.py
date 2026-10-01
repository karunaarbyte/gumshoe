import json
import os
from pathlib import Path

import pytest

from gumshoe.config import Settings

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Every environment variable Settings reads (field names are matched case-insensitively).
SETTINGS_ENV_VARS = {name.upper() for name in Settings.model_fields}


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
