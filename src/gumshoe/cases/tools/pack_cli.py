"""`python -m gumshoe.cases packs check pack.toml`: every issue with its key path."""

import sys
from collections.abc import Callable
from pathlib import Path

from gumshoe.cases.packs import load_pack
from gumshoe.cases.packs.issues import PackSeverity


def run_pack_check(path: Path, out: Callable[[str], None] = print) -> int:
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 2
    result = load_pack(data)
    for issue in result.issues:
        out(f"{issue.severity.value:7} {issue.code:26} {issue.path}")
        out(f"        {issue.message}")
        if issue.suggestion:
            out(f"        {issue.suggestion}")
    errors = sum(1 for i in result.issues if i.severity is PackSeverity.ERROR)
    out("ok" if errors == 0 else f"{errors} error(s)")
    return 0 if errors == 0 else 1
