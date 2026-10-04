import json

from tests.generate.update_golden import GOLDEN, stage_digests


def test_the_stage_digests_match_the_committed_snapshot():
    assert json.loads(GOLDEN.read_text()) == stage_digests()


def test_the_snapshot_covers_five_seeds_per_preset_and_three_stages():
    snapshot = json.loads(GOLDEN.read_text())
    assert len(snapshot) == 15 and all(len(stages) == 3 for stages in snapshot.values())
    assert len({d for stages in snapshot.values() for d in stages.values()}) == 45  # all distinct
