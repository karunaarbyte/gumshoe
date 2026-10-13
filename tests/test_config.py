import pytest
from pydantic import ValidationError

from gumshoe.config import Settings, get_settings


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


def test_get_settings_is_cached(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here, so the developer's real .env is not read
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


@pytest.mark.parametrize("bad", ["0", "-5", "nan"])
def test_timeout_must_be_a_positive_number(monkeypatch, bad):
    monkeypatch.setenv("REQUEST_TIMEOUT_S", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_stats_defaults():
    s = Settings(_env_file=None)
    assert s.stats_db_path.as_posix() == "data/decisions.db"
    assert s.cold_after_s == 300.0


@pytest.mark.parametrize("bad", ["0", "-1", "nan", "inf"])
def test_cold_after_must_be_positive_and_finite(monkeypatch, bad):
    monkeypatch.setenv("COLD_AFTER_S", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_agent_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ollama_base_url == "http://localhost:11434/v1"
    assert s.persona_model_default == "ministral-3:14b"
    assert s.persona_model_dramatic == "gemma4:12b"
    assert (s.dramatic_from, s.confidence_gate, s.confirm_gate) == (2.5, 0.6, 0.8)
    assert (s.max_redrafts, s.llm_timeout_s) == (3, 60.0)


def test_agent_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PERSONA_MODEL_DEFAULT", "small")
    monkeypatch.setenv("CONFIRM_GATE", "0.9")
    monkeypatch.setenv("MAX_REDRAFTS", "0")
    s = Settings(_env_file=None)
    assert (s.persona_model_default, s.confirm_gate, s.max_redrafts) == ("small", 0.9, 0)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CONFIRM_GATE", "0.5"),  # yes and no bands would touch
        ("CONFIRM_GATE", "1.1"),
        ("CONFIDENCE_GATE", "0"),
        ("CONFIDENCE_GATE", "1.5"),
        ("MAX_REDRAFTS", "-1"),
        ("MAX_REDRAFTS", "11"),
        ("DRAMATIC_FROM", "5"),
        ("DRAMATIC_FROM", "-1"),
        ("DRAMATIC_FROM", "nan"),
        ("LLM_TIMEOUT_S", "0"),
        ("LLM_TIMEOUT_S", "inf"),
    ],
)
def test_agent_settings_reject_values_out_of_range(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
