"""`python -m gumshoe.cases validate case.json`: a developer report. Never shown to players."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import load_case
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Profile, Report
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
