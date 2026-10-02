"""Write the pack code catalogue as Markdown: `uv run python -m tests.packs.dump_catalogue OUT`."""

import sys
from pathlib import Path

from gumshoe.cases.packs.catalogue import PACK_CATALOGUE


def render() -> str:
    lines = [
        "# Pack issue-code catalogue (generated)",
        "",
        "| code | stage | severity | meaning |",
        "|---|---|---|---|",
    ]
    for spec in sorted(PACK_CATALOGUE.values(), key=lambda s: (s.stage, s.code)):
        lines.append(f"| {spec.code} | {spec.stage} | {spec.severity.value} | {spec.message} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(render())
    print("wrote", out, len(PACK_CATALOGUE), "codes")
