"""python -m gumshoe.mcp_server [--saves DIR]: serve the game over stdio.

stdout carries the protocol, so nothing here prints; the SDK logs to stderr.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from gumshoe.mcp_server.host import GameHost
from gumshoe.mcp_server.tools import build_server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gumshoe.mcp_server", description=__doc__)
    parser.add_argument(
        "--saves",
        type=Path,
        help="saves directory (default: $GUMSHOE_SAVES, else ./saves, relative to the server's "
        "working directory; pass an absolute path when a client launches the server from "
        "elsewhere)",
    )
    args = parser.parse_args(argv)
    build_server(GameHost(saves_dir=args.saves)).run("stdio")


if __name__ == "__main__":
    main()
