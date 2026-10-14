"""HTTP API: the game (each turn streamed as server-sent events) and the decision stats."""

from gumshoe.api.app import create_app

__all__ = ["create_app"]
