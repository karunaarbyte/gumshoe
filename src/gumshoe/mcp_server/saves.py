"""The save file: one JSON document per game, written atomically into the saves directory.

A save holds the full skeleton, so it is spoiler-bearing on disk. No tool takes a path: the host
makes the name, and `read_save` accepts only a name of the exact shape it makes.
"""

import contextlib
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from gumshoe.cases import View
from gumshoe.mcp_server.errors import GameError

SAVE_FORMAT = 1
NAME = re.compile(r"[0-9a-f]{16}")
ENV_VAR = "GUMSHOE_SAVES"


class SaveRef(View):
    name: str


class SaveFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    save_format: Literal[1]
    pack: str
    case: str  # the case's canonical JSON
    state: str  # GameSession.state_json()


def default_saves_dir() -> Path:
    return Path(os.environ.get(ENV_VAR) or "saves")


def path_for(folder: Path, name: str) -> Path:
    return folder / f"{name}.json"


def check_name(name: str) -> None:
    if not isinstance(name, str) or NAME.fullmatch(name) is None:
        raise GameError("bad_argument", "a save name is 16 lowercase hex characters")


def write_save(folder: Path, name: str, save: SaveFile) -> None:
    """Create the folder if needed, write beside the target, then replace it in one step."""
    temp = folder / f".{name}.tmp"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temp.write_text(save.model_dump_json(), encoding="utf-8")
        os.replace(temp, path_for(folder, name))
    except OSError as exc:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise GameError("bad_save", "the save could not be written") from exc


def read_save(folder: Path, name: str) -> SaveFile:
    check_name(name)
    try:
        text = path_for(folder, name).read_bytes().decode("utf-8")
        return SaveFile.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise GameError("bad_save", "that save cannot be read") from exc
