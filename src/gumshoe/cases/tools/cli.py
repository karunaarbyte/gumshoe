"""`python -m gumshoe.cases validate|simulate|play`: validate and simulate are developer reports,
never shown to players; play is the player surface and reads only what a player may see."""

import argparse
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from gumshoe.cases.generate.api import CaseGenerationError, generate
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import dump_case, load_case
from gumshoe.cases.model.spec import PRESET_ORDER, UnsupportedPreset
from gumshoe.cases.play import load_session
from gumshoe.cases.tools.builtin import BuiltinPackError, load_builtin_pack
from gumshoe.cases.tools.case_text import render_case
from gumshoe.cases.tools.dev import simulate_lines
from gumshoe.cases.tools.gen_dev import smoke
from gumshoe.cases.tools.pack_cli import run_pack_check
from gumshoe.cases.tools.play_cli import run_play
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Profile, Report, Severity
from gumshoe.cases.validate.runner import validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m gumshoe.cases")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="validate a case file")
    check.add_argument("path", type=Path)
    check.add_argument(
        "--profile", choices=[p.value for p in Profile], default=Profile.STRICT.value
    )
    check.add_argument("--pack", type=Path, help="pack JSON enabling the pack-bound rules")
    check.add_argument(
        "--dev", action="store_true", help="also show spoiler issues (they name the truth)"
    )
    check.set_defaults(handler=_validate)
    play = sub.add_parser("play", help="play a case in the terminal")
    play.add_argument("path", type=Path)
    play.add_argument("--salt", help="seed for the opaque handles (random by default)")
    play.set_defaults(handler=_play)
    simulate = sub.add_parser(
        "simulate", help="developer report: solvability, cheapest play, blind guess"
    )
    simulate.add_argument("path", type=Path)
    simulate.set_defaults(handler=_simulate)
    gen = sub.add_parser("generate", help="developer: generate a case (it names the truth)")
    gen.add_argument("seed", type=int)
    gen.add_argument("--preset", choices=PRESET_ORDER, default="standard")
    gen.add_argument("--pack", default="castle", help="name of a bundled pack")
    gen.add_argument("-o", "--output", type=Path, help="write the case here instead of stdout")
    gen.add_argument("--text", action="store_true", help="print the case as readable text")
    gen.set_defaults(handler=_generate)
    smoke_cmd = sub.add_parser("smoke", help="developer: attempts and failures over a run of seeds")
    smoke_cmd.add_argument("--preset", choices=PRESET_ORDER, default="standard")
    smoke_cmd.add_argument("--pack", default="castle", help="name of a bundled pack")
    smoke_cmd.add_argument("--seeds", type=int, default=200, help="seeds 0 up to this number")
    smoke_cmd.set_defaults(handler=_smoke)
    packs = sub.add_parser("packs", help="work with theme packs")
    packs_sub = packs.add_subparsers(dest="packs_command", required=True)
    pack_check = packs_sub.add_parser("check", help="check a pack file and list every issue")
    pack_check.add_argument("path", type=Path)
    pack_check.set_defaults(handler=_packs_check)
    return parser


def _format(report: Report, dev: bool) -> list[str]:
    lines: list[str] = []
    hidden = 0
    for issue in report.issues:
        if issue.spoiler and not dev:
            hidden += 1
            continue
        axis = f" [{issue.axis.value}]" if issue.axis else ""
        params = " ".join(f"{k}={v}" for k, v in issue.params)
        lines.append(
            f"{issue.severity.value:7} {issue.code:28}{axis} "
            f"{', '.join(issue.subjects)} {params}".rstrip()
        )
        lines.append(f"        {CATALOGUE[issue.code].message}")
    if hidden:
        lines.append(f"({hidden} spoiler issue(s) hidden; pass --dev to show them)")
    if report.skipped_groups:
        lines.append(f"(skipped groups: {', '.join(str(g) for g in report.skipped_groups)})")
    return lines


def _validate(args: argparse.Namespace) -> int:
    try:
        case = load_case(args.path.read_bytes())
        pack = Pack.model_validate_json(args.pack.read_bytes()) if args.pack else None
    except OSError as exc:
        print(f"error: cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "input"
        print(f"error: not a valid case/pack file ({where}: {first['msg']})", file=sys.stderr)
        return 2
    report = validate(case, pack, Profile(args.profile))
    for line in _format(report, args.dev):
        print(line)
    print(
        "ok"
        if report.ok
        else f"{sum(1 for i in report.issues if i.severity.value == 'error')} error(s)"
    )
    return 0 if report.ok else 1


def _read_case_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return None


def _load_playable(path: Path) -> tuple[bytes, Case] | None:
    """Read and parse a case, refusing (with the code on stderr) one group 1 calls broken."""
    data = _read_case_bytes(path)
    if data is None:
        return None
    try:
        case = load_case(data)
    except ValidationError as exc:
        print(f"error: not a valid case file ({exc.errors()[0]['msg']})", file=sys.stderr)
        return None
    structural = [
        i
        for i in validate(case, None, Profile.CUSTOM).issues
        if i.group == 1 and i.severity is Severity.ERROR
    ]
    if structural:
        print(f"error: the case is structurally broken ({structural[0].code})", file=sys.stderr)
        return None
    return data, case


def _play(args: argparse.Namespace) -> int:
    loaded = _load_playable(args.path)
    if loaded is None:
        return 2
    try:  # a handle collision, or (pydantic's ValidationError is one) a bad state
        session = load_session(loaded[0], args.salt or secrets.token_hex(8))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_play(session, input, print)


def _simulate(args: argparse.Namespace) -> int:
    loaded = _load_playable(args.path)
    if loaded is None:
        return 2
    for line in simulate_lines(loaded[1]):
        print(line)
    return 0


def _generate(args: argparse.Namespace) -> int:
    try:
        pack = load_builtin_pack(args.pack)
        case = generate(args.seed, args.preset, pack)
    except (BuiltinPackError, UnsupportedPreset, CaseGenerationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.text:
        print("\n".join(render_case(case, pack)))
        return 0
    data = dump_case(case)
    if args.output is None:
        print(data.decode("utf-8"))
        return 0
    try:
        args.output.write_bytes(data)
    except OSError as exc:
        print(f"error: cannot write {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 2
    return 0


def _smoke(args: argparse.Namespace) -> int:
    try:
        report = smoke(load_builtin_pack(args.pack), args.preset, range(args.seeds))
    except (BuiltinPackError, UnsupportedPreset) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


def _packs_check(args: argparse.Namespace) -> int:
    return run_pack_check(args.path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
