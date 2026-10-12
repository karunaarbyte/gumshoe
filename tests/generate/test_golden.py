import json

from tests.generate.update_golden import GOLDEN, stage_digests


def test_the_stage_digests_match_the_committed_snapshot():
    assert json.loads(GOLDEN.read_text()) == stage_digests()


def test_the_snapshot_covers_five_seeds_per_preset_every_stage_and_both_cases():
    snapshot = json.loads(GOLDEN.read_text())
    keys = {"roster", "truth", "timeline", "facts", "placement", "gating", "case", "final", "skin"}
    assert len(snapshot) == 15 and all(set(stages) == keys for stages in snapshot.values())
    # gating only wires, so two cases at depth 0 share it; every other digest is distinct
    varied = [d for stages in snapshot.values() for k, d in stages.items() if k != "gating"]
    assert len(set(varied)) == len(varied) == 120
