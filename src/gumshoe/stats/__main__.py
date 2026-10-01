"""python -m gumshoe.stats battery [--rounds N]"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from functools import partial

from gumshoe.config import get_settings
from gumshoe.decider import DeciderError, ShadowDecider, make_decider
from gumshoe.stats.battery import run_battery
from gumshoe.stats.store import SqliteStatsStore

# How long past the request timeout to wait for a shadow call before giving up on it.
SETTLE_SLACK_S = 5.0


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m gumshoe.stats")
    sub = parser.add_subparsers(dest="command", required=True)
    battery = sub.add_parser("battery", help="run fixed player inputs through shadow mode")
    battery.add_argument("--rounds", type=positive_int, default=1, help="repeat the set N times")
    return parser


async def _battery(rounds: int) -> int:
    settings = get_settings()
    store = SqliteStatsStore(settings.stats_db_path)
    decider = make_decider(settings, recorder=store)
    try:
        # let each shadow call finish before the next decision (see run_battery), but never forever
        settle = None
        if isinstance(decider, ShadowDecider):
            settle = partial(decider.drain, settings.request_timeout_s + SETTLE_SLACK_S)
        outcome = await run_battery(decider, rounds, settle=settle)
    finally:
        await decider.aclose()  # waits for shadow calls still being recorded
    if outcome.failed == outcome.attempted:  # nothing worked: a setup problem, not flakiness
        print(
            f"error: all {outcome.attempted} decisions failed; last error: {outcome.last_error}",
            file=sys.stderr,
        )
        return 1
    print(
        f"ran {outcome.attempted} decisions ({outcome.failed} failed) into {settings.stats_db_path}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_battery(args.rounds))
    except DeciderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
