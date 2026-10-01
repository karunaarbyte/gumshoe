import pytest
from pydantic import ValidationError

from gumshoe.config import Settings, get_settings

ENV_VARS = [
    "DECIDER_PRIMARY", "DECIDER_SHADOW", "JEV_BASE_URL", "JEV_API_KEY", "JEV_MODEL",
    "NIMBLE_BASE_URL", "NIMBLE_MODEL", "REQUEST_TIMEOUT_S",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults():
    s = Settings(_env_file=None)
    assert s.decider_primary == "jev"
    assert s.decider_shadow == "nimble"
    assert s.nimble_base_url == "http://localhost:11434/v1"
    assert s.nimble_model == "nimble"
    assert s.jev_base_url == "https://api.typesafe.ai/v1"
    assert s.jev_model == "jev-latest"
    assert s.request_timeout_s == 30.0


def test_env_overrides_and_converts_types(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "nimble")
    monkeypatch.setenv("DECIDER_SHADOW", "jev")
    monkeypatch.setenv("REQUEST_TIMEOUT_S", "5")
    s = Settings(_env_file=None)
    assert s.decider_primary == "nimble"
    assert s.decider_shadow == "jev"
    assert s.request_timeout_s == 5.0


def test_blank_shadow_turns_shadowing_off(monkeypatch):
    monkeypatch.setenv("DECIDER_SHADOW", "")
    assert Settings(_env_file=None).decider_shadow is None


def test_primary_and_shadow_must_differ(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "nimble")  # shadow defaults to nimble too
    with pytest.raises(ValidationError, match="DECIDER_SHADOW"):
        Settings(_env_file=None)


def test_invalid_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "gpt")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_never_appears_in_repr_or_str(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "s3cret-key")
    s = Settings(_env_file=None)
    assert "s3cret-key" not in repr(s)
    assert "s3cret-key" not in str(s)
    assert s.jev_api_key.get_secret_value() == "s3cret-key"


def test_reads_values_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DECIDER_PRIMARY=nimble\nDECIDER_SHADOW=\n")
    s = Settings(_env_file=env)
    assert s.decider_primary == "nimble"
    assert s.decider_shadow is None


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
