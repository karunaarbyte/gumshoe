from gumshoe.agent import AgentConfig
from gumshoe.api.wiring import agent_config
from gumshoe.config import Settings


def test_default_settings_give_the_default_agent_config():
    assert agent_config(Settings(_env_file=None)) == AgentConfig()


def test_every_agent_setting_reaches_the_config(monkeypatch):
    monkeypatch.setenv("CONFIDENCE_GATE", "0.7")
    monkeypatch.setenv("CONFIRM_GATE", "0.9")
    monkeypatch.setenv("MAX_REDRAFTS", "1")
    monkeypatch.setenv("DRAMATIC_FROM", "3")
    monkeypatch.setenv("PERSONA_MODEL_DEFAULT", "a")
    monkeypatch.setenv("PERSONA_MODEL_DRAMATIC", "b")
    config = agent_config(Settings(_env_file=None))
    assert config == AgentConfig(
        confidence_gate=0.7,
        confirm_gate=0.9,
        max_redrafts=1,
        dramatic_from=3.0,
        model_default="a",
        model_dramatic="b",
    )
