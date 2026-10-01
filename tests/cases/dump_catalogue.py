"""Write the issue-code catalogue as Markdown: `uv run python tests/cases/dump_catalogue.py OUT`."""

import sys
from pathlib import Path

from gumshoe.cases.validate.catalogue import CATALOGUE


def render() -> str:
    lines = [
        "# Case engine issue-code catalogue (generated)",
        "",
        "| code | group | strict | imported | fix stage | hint | spoiler | needs pack | meaning |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for spec in sorted(CATALOGUE.values(), key=lambda s: (s.group, s.code)):
        lines.append(
            f"| {spec.code} | {spec.group} | {spec.severity_strict.value} "
            f"| {spec.severity_imported.value} | {spec.fix_stage.value} | {spec.hint.value} "
            f"| {'yes' if spec.spoiler else ''} | {'yes' if spec.requires_pack else ''} "
            f"| {spec.message} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(render())
    print("wrote", out, len(CATALOGUE), "codes")
