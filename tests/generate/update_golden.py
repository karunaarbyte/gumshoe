"""Regenerate the stage digests: `uv run python -m tests.generate.update_golden`."""

import json
from pathlib import Path

from gumshoe.cases.generate import facts as facts_stage
from gumshoe.cases.generate import placement as placement_stage
from gumshoe.cases.generate.gen_context import GenContext
from tests.generate.helpers import GOLDEN_SEEDS, PRESET_NAMES, castle, stages

GOLDEN = Path(__file__).parent / "golden" / "castle_stages.json"


def stage_digests() -> dict[str, dict[str, str]]:
    pack = castle()
    found: dict[str, dict[str, str]] = {}
    for preset in PRESET_NAMES:
        for seed in GOLDEN_SEEDS:
            ctx = GenContext.of(pack, seed, preset)
            roster, truth, timeline = stages(ctx)
            facts = facts_stage.run(ctx, ctx.stream("facts"), truth, timeline)
            placed = placement_stage.run(ctx, ctx.stream("placement"), truth, facts)
            found[f"{preset}/{seed}"] = {
                "roster": roster.digest(),
                "truth": truth.digest(),
                "timeline": timeline.digest(),
                "facts": facts.digest(),
                "placement": placed.digest(),
            }
    return found


if __name__ == "__main__":
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(stage_digests(), indent=2, sort_keys=True) + "\n")
    print("wrote", GOLDEN)
