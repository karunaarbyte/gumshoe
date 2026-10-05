"""Regenerate the stage digests: `uv run python -m tests.generate.update_golden`."""

import json
from pathlib import Path

from gumshoe.cases.generate.api import generate
from gumshoe.cases.generate.assemble import build_case
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.model.serialize import skeleton_digest
from tests.generate.helpers import GOLDEN_SEEDS, PRESET_NAMES, castle, gating_of, stages

GOLDEN = Path(__file__).parent / "golden" / "castle_stages.json"


def stage_digests() -> dict[str, dict[str, str]]:
    pack = castle()
    found: dict[str, dict[str, str]] = {}
    for preset in PRESET_NAMES:
        for seed in GOLDEN_SEEDS:
            ctx = GenContext.of(pack, seed, preset)
            roster, _, _ = stages(ctx)
            outputs = gating_of(ctx)
            truth, timeline, facts, placed, gates = outputs
            found[f"{preset}/{seed}"] = {
                "roster": roster.digest(),
                "truth": truth.digest(),
                "timeline": timeline.digest(),
                "facts": facts.digest(),
                "placement": placed.digest(),
                "gating": gates.digest(),
                "case": skeleton_digest(build_case(ctx, *outputs)),
                "final": skeleton_digest(generate(seed, preset, pack)),
            }
    return found


if __name__ == "__main__":
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(stage_digests(), indent=2, sort_keys=True) + "\n")
    print("wrote", GOLDEN)
