from pathlib import Path

from tests.packs.dump_catalogue import render

GOLDEN = Path(__file__).parent / "golden" / "catalogue.md"
REGEN = "uv run python -m tests.packs.dump_catalogue tests/packs/golden/catalogue.md"


def test_the_generated_catalogue_matches_the_golden_file():
    assert render() == GOLDEN.read_text(), f"regenerate with: {REGEN}"
