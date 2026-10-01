"""Command line interface: ask one backend, or compare both."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from pathlib import Path

from pydantic import TypeAdapter

from gumshoe.config import get_settings
from gumshoe.decider.base import Decider
from gumshoe.decider.compare import Outcome, compare_backends
from gumshoe.decider.errors import DeciderConfigError, DeciderError
from gumshoe.decider.factory import make_decider
from gumshoe.decider.models import Question
from gumshoe.decider.render import format_comparison, format_result
from gumshoe.decider.samples import DEMO_QUESTIONS

QUESTIONS_ADAPTER = TypeAdapter(dict[str, Question])
BACKENDS = ("nimble", "jev")


def load_questions(path: Path | None) -> dict[str, Question]:
    if path is None:
        return dict(DEMO_QUESTIONS)
    return QUESTIONS_ADAPTER.validate_json(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m gumshoe.decider")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="send a state to one backend")
    ask.add_argument("state")
    ask.add_argument("--backend", choices=BACKENDS, help="default: DECIDER_PRIMARY from .env")
    ask.add_argument("--questions", type=Path, help="JSON file of questions (default: demo set)")
    ask.set_defaults(handler=_ask)

    compare = sub.add_parser("compare", help="send a state to both backends")
    compare.add_argument("state")
    compare.add_argument("--questions", type=Path, help="JSON file of questions (default: demo set)")
    compare.set_defaults(handler=_compare)
    return parser


async def _ask(args: argparse.Namespace) -> int:
    decider = make_decider(get_settings(), args.backend)
    try:
        result = await decider.decide(args.state, load_questions(args.questions), node="cli")
    finally:
        await decider.aclose()
    print(f"backend: {decider.name}")
    print(format_result(result))
    return 0


async def _compare(args: argparse.Namespace) -> int:
    settings = get_settings()
    questions = load_questions(args.questions)
    outcomes: dict[str, Outcome] = {}
    deciders: dict[str, Decider] = {}
    async with AsyncExitStack() as stack:
        for backend in BACKENDS:
            try:
                decider = make_decider(settings, backend)
            except DeciderConfigError as exc:
                outcomes[backend] = Outcome(error=str(exc))
                continue
            stack.push_async_callback(decider.aclose)
            deciders[backend] = decider
        outcomes |= await compare_backends(deciders, args.state, questions)
    print(format_comparison({b: outcomes[b] for b in BACKENDS}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.handler(args))
    except DeciderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
