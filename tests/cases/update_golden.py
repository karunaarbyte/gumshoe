"""Regenerate the golden snapshot and digest: `uv run python -m tests.cases.update_golden`."""

from pathlib import Path

from gumshoe.cases.model.serialize import dump_case, skeleton_digest
from tests.cases.fixtures import build_case

DATA = Path(__file__).parent / "golden"

if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    case = build_case()
    (DATA / "manor_small.json").write_bytes(dump_case(case))
    (DATA / "manor_small.digest").write_text(skeleton_digest(case) + "\n")
    print("wrote", DATA / "manor_small.json", skeleton_digest(case))
