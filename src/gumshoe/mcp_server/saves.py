"""The save file: one JSON document per game, written atomically into the saves directory.

A save holds the full skeleton, so it is spoiler-bearing on disk. No tool takes a path: the host
makes the name, and `read_save` accepts only a name of the exact shape it makes.
"""

import contextlib
import os
import re
import secrets
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


def write_save(folder: Path, name: str, save: SaveFile) -> None:
    """Create the folder if needed, write and sync beside the target, then link it into place.

    A hard link fails if the target exists, so two processes can never overwrite each other's
    save. The temp name is unique, so a crashed run leaves nothing a later run trips over.
    """
    temp = folder / f".{name}.{secrets.token_hex(4)}.tmp"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(save.model_dump_json())
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path_for(folder, name))
        except FileExistsError as exc:
            raise SaveExists(name) from exc
    except OSError as exc:
        raise GameError("bad_save", "the save could not be written") from exc
    finally:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)


def read_save(folder: Path, name: str) -> SaveFile:
    check_name(name)
    try:
        text = path_for(folder, name).read_bytes().decode("utf-8")
        return SaveFile.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise GameError("bad_save", "that save cannot be read") from exc
