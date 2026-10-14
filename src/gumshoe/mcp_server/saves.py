"""The save file: one JSON document per game, written atomically into the saves directory.

A save holds the full skeleton, so it is spoiler-bearing on disk. No tool takes a path: the host
makes the name, and `read_save` accepts only a name of the exact shape it makes.
"""

import contextlib
import errno
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from gumshoe.cases import View
from gumshoe.mcp_server.errors import GameError

SAVE_FORMAT = 1
NAME = re.compile(r"[0-9a-f]{16}")
# The same variables, in the same order, as `gumshoe.config.Settings.saves_dir` (which also reads
# them from `.env`; this module cannot, so the API passes its settings' folder explicitly).
ENV_VARS = ("SAVES_DIR", "GUMSHOE_SAVES")
# src/gumshoe/mcp_server/saves.py -> the repository root, as `gumshoe.config.PROJECT_ROOT`
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_SAVE_BYTES = 1_000_000  # a real save is about 40 KB
MAX_SAVES = 500
# os.link fails with these where the filesystem has no hard links (FAT, some network mounts)
NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS})


class SaveRef(View):
    name: str


class SaveFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    save_format: Literal[1]
    pack: str
    case: str  # the case's canonical JSON
    state: str  # GameSession.state_json()


def default_saves_dir() -> Path:
    """$SAVES_DIR, else $GUMSHOE_SAVES, else `saves`; relative to the project root."""
    raw = next((os.environ[var] for var in ENV_VARS if var in os.environ), "") or "saves"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def path_for(folder: Path, name: str) -> Path:
    return folder / f"{name}.json"


def check_name(name: str) -> None:
    if not isinstance(name, str) or NAME.fullmatch(name) is None:
        raise GameError("bad_argument", "a save name is 16 lowercase hex characters")


class SaveExists(Exception):
    """The name is taken (another process made it first); the caller draws another name."""


def count_saves(folder: Path) -> int:
    """How many saves the folder holds (files named like a save; 0 if there is no folder)."""
    try:
        return sum(1 for p in folder.glob("*.json") if NAME.fullmatch(p.stem))
    except OSError:
        return 0


def _publish(temp: Path, target: Path) -> None:
    """Move the finished temp file to `target`, never replacing an existing file.

    A hard link fails if the target exists, so two processes can never overwrite each other's
    save. Where the filesystem has no hard links, an exclusive create claims the name first and
    a rename then fills it (a reader may briefly see it empty, which reads as a bad save).
    """
    try:
        os.link(temp, target)
        return
    except FileExistsError as exc:
        raise SaveExists(target.stem) from exc
    except OSError as exc:
        if exc.errno not in NO_HARD_LINKS:
            raise
    try:
        os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError as exc:
        raise SaveExists(target.stem) from exc
    os.replace(temp, target)


def write_save(folder: Path, name: str, save: SaveFile) -> None:
    """Create the folder if needed (owner-only), write and sync beside the target (owner-only:
    a save is spoiler-bearing), then publish it. The temp name is unique, so a crashed run
    leaves nothing a later run trips over."""
    temp = folder / f".{name}.{secrets.token_hex(4)}.tmp"
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(save.model_dump_json())
            handle.flush()
            os.fsync(handle.fileno())
        _publish(temp, path_for(folder, name))
    except OSError as exc:
        raise GameError("bad_save", "the save could not be written") from exc
    finally:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)


def read_save(folder: Path, name: str) -> SaveFile:
    """Read a save by name. Only a regular file of at most MAX_SAVE_BYTES is read at all."""
    check_name(name)
    path = path_for(folder, name)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SAVE_BYTES:
            raise GameError("bad_save", "that save cannot be read")
        with path.open("rb") as handle:
            data = handle.read(MAX_SAVE_BYTES + 1)
        if len(data) > MAX_SAVE_BYTES:  # it grew after the stat
            raise GameError("bad_save", "that save cannot be read")
        return SaveFile.model_validate_json(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise GameError("bad_save", "that save cannot be read") from exc
