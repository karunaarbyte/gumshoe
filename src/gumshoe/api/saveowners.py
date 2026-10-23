"""Who owns which save. A save file is named by the game host and says nothing about its owner,
so a sidecar `<name>.owner` beside it holds a keyed hash of the owner's session id (never the id).
A save with no sidecar belongs to nobody."""

import contextlib
import hmac
import os
import re
import secrets
import stat
import time
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

    def claim(self, name: str, owner: str, ip: str = "") -> None:
        path = self._path(name)
        tags = [self._sessions.owner_tag(owner), self._sessions.owner_tag(ip) if ip else ""]
        temp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            temp.write_text("\n".join(tags))
            os.replace(temp, path)
        finally:
            with contextlib.suppress(OSError):
                temp.unlink()

    def _tags(self, path: Path) -> tuple[str, str]:
        """(owner tag, ip tag) from a sidecar; a damaged or missing one yields empty tags."""
        try:
            lines = path.read_text().split("\n")
        except (OSError, UnicodeDecodeError):
            return "", ""
        return lines[0], lines[1] if len(lines) > 1 else ""

    def owns(self, name: str, owner: str) -> bool:
        try:
            first, _ = self._tags(self._path(name))
        except ValueError:
            return False
        expected = self._sessions.owner_tag(owner)
        return hmac.compare_digest(first.encode(), expected.encode())

    def _sidecars(self) -> list[Path]:
        if not self._folder.is_dir():
            return []
        return [
            p for p in self._folder.glob("*.owner") if NAME.fullmatch(p.stem) and not p.is_symlink()
        ]

    def count_all(self) -> int:
        """The saves held: `<name>.json` files with a name the host makes."""
        if not self._folder.is_dir():
            return 0
        return sum(1 for p in self._folder.glob("*.json") if NAME.fullmatch(p.stem))

    def count_owned(self, owner: str) -> int:
        tag = self._sessions.owner_tag(owner)
        return sum(1 for p in self._sidecars() if self._tags(p)[0] == tag)

    def count_ip(self, ip: str) -> int:
        if not ip:
            return 0
        tag = self._sessions.owner_tag(ip)
        return sum(1 for p in self._sidecars() if self._tags(p)[1] == tag)

    def delete(self, name: str) -> None:
        sidecar = self._path(name)  # validates the name before any other path is built
        for path in (self._folder / f"{name}.json", sidecar):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()  # a symlink is removed itself, never followed

    def purge(self, older_than_s: float, now: float | None = None) -> int:
        """Delete saves older than `older_than_s` (by file time) and sidecars with no save.

        Only names the host makes are touched, symlinks are skipped, and a file that vanishes
        mid-purge is not an error."""
        now = time.time() if now is None else now
        removed = 0
        if not self._folder.is_dir():
            return 0
        for save in self._folder.glob("*.json"):
            if not NAME.fullmatch(save.stem):
                continue  # not a name the host makes: not ours to delete
            try:
                info = save.lstat()
                if stat.S_ISREG(info.st_mode) and now - info.st_mtime > older_than_s:
                    self.delete(save.stem)  # owned or not: a save from before owners, or a crash
                    removed += 1
            except OSError:
                continue
        for sidecar in self._sidecars():
            try:
                (self._folder / f"{sidecar.stem}.json").lstat()
            except FileNotFoundError:
                with contextlib.suppress(OSError):
                    sidecar.unlink(missing_ok=True)
            except OSError:
                continue
        return removed
