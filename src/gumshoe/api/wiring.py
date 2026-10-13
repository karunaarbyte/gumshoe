"""Builds the real agent service from settings. The only api module that touches the MCP SDK."""

from gumshoe.agent import AgentConfig
from gumshoe.config import Settings


def agent_config(settings: Settings) -> AgentConfig:
    return AgentConfig(
        confidence_gate=settings.confidence_gate,
        confirm_gate=settings.confirm_gate,
        max_redrafts=settings.max_redrafts,
        dramatic_from=settings.dramatic_from,
        model_default=settings.persona_model_default,
        model_dramatic=settings.persona_model_dramatic,
    )
