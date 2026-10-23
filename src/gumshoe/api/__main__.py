"""python -m gumshoe.api [--host HOST] [--port PORT] [--reload]   (also installed as gumshoe-api)

Host and port default to API_HOST and API_PORT (127.0.0.1:8000). There is no authentication:
bind to anything other than the loopback address only on a network you trust.
"""

import argparse
from collections.abc import Sequence

import uvicorn
from fastapi import FastAPI

from gumshoe.api.app import create_app
from gumshoe.config import Settings, get_settings
from gumshoe.stats import SqliteStatsStore

APP = "gumshoe.api.__main__:build_app"


def build_app() -> FastAPI:
    """The app uvicorn serves. A factory named by import string, so --reload can rebuild it."""
    settings = get_settings()
    return create_app(SqliteStatsStore(settings.stats_db_path), settings=settings)


def build_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gumshoe-api", description="Serve the Gumshoe API.")
    parser.add_argument("--host", default=settings.api_host, help="default: API_HOST")
    parser.add_argument("--port", type=int, default=settings.api_port, help="default: API_PORT")
    parser.add_argument(
        "--reload", action="store_true", help="restart when the code changes (development)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser(get_settings()).parse_args(argv)
    uvicorn.run(
        APP,
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
