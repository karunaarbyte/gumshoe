"""Shared pieces for the MCP server tests."""

from gumshoe.mcp_server import GameHost


class SeqIds:
    """A pinned id source: 0000000000000001, 0000000000000002, ... (16 hex characters each)."""

    def __init__(self, start: int = 1) -> None:
        self.n = start

    def next(self) -> str:
        value = f"{self.n:016x}"
        self.n += 1
        return value


def make_host() -> GameHost:
    return GameHost(ids=SeqIds())
