"""python -m gumshoe.mcp_server [--saves DIR]: serve the game over stdio.

stdout carries the protocol, so nothing here prints; the SDK logs to stderr.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from gumshoe.cases import BuiltinPackError, bundled_packs
from gumshoe.mcp_server.host import GameHost
from gumshoe.mcp_server.tools import build_server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gumshoe.mcp_server", description=__doc__)
    parser.add_argument(
        "--saves",
        type=Path,
        help="saves directory (default: $SAVES_DIR, else $GUMSHOE_SAVES, else saves; a relative "
        "default is resolved against the project root, a relative --saves against the working "
        "directory)",
    )
    args = parser.parse_args(argv)
    try:
        bundled_packs()  # a broken bundled pack stops startup; stderr only, stdout is the protocol
    except BuiltinPackError as exc:
        raise SystemExit(f"error: {exc}") from exc
    build_server(GameHost(saves_dir=args.saves)).run("stdio")


if __name__ == "__main__":
    main()
