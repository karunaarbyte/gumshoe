"""Regenerate the stage digests: `uv run python -m tests.generate.update_golden`."""

import json
from pathlib import Path

from gumshoe.cases.generate.gen_context import GenContext
from tests.generate.helpers import GOLDEN_SEEDS, PRESET_NAMES, castle, stages

GOLDEN = Path(__file__).parent / "golden" / "castle_stages.json"


def stage_digests() -> dict[str, dict[str, str]]:
    pack = castle()
    found: dict[str, dict[str, str]] = {}
    for preset in PRESET_NAMES:
        for seed in GOLDEN_SEEDS:
            roster, truth, timeline = stages(GenContext.of(pack, seed, preset))
            found[f"{preset}/{seed}"] = {
                "roster": roster.digest(),
                "truth": truth.digest(),
                "timeline": timeline.digest(),
            }
    return found


if __name__ == "__main__":
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(stage_digests(), indent=2, sort_keys=True) + "\n")
    print("wrote", GOLDEN)
