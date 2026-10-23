"""Who owns which save. A save file is named by the game host and says nothing about its owner,
so a sidecar `<name>.owner` beside it holds a keyed hash of the owner's session id (never the id).
A save with no sidecar belongs to nobody."""

import contextlib
import hmac
import os
import re
import secrets
from pathlib import Path

from gumshoe.api.session import Sessions

# The shape of a save name the game host makes (`gumshoe.mcp_server.saves.NAME`). Copied here
# because only `api/wiring.py` may import the MCP server (tests/test_architecture.py).
NAME = re.compile(r"[0-9a-f]{16}")


class SaveOwners:
    def __init__(self, folder: Path, sessions: Sessions) -> None:
        self._folder = folder
        self._sessions = sessions

    def _path(self, name: str) -> Path:
        if NAME.fullmatch(name) is None:
            raise ValueError("not a save name")
        return self._folder / f"{name}.owner"

    def claim(self, name: str, owner: str) -> None:
        path = self._path(name)
        tag = self._sessions.owner_tag(owner)
        temp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            temp.write_text(tag)
            os.replace(temp, path)
        finally:
            with contextlib.suppress(OSError):
                temp.unlink()

    def owns(self, name: str, owner: str) -> bool:
        try:
            stored = self._path(name).read_text()
        except (ValueError, OSError, UnicodeDecodeError):
            return False
        expected = self._sessions.owner_tag(owner)
        return hmac.compare_digest(stored.encode(), expected.encode())
