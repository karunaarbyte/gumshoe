import pytest
from pydantic import ValidationError

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import TruthOut
from tests.generate.helpers import castle, stages


def test_a_digest_is_stable_and_follows_the_content():
    ctx = GenContext.of(castle(), 2, "short")
    roster, truth, timeline = stages(ctx)
    assert roster.digest() == stages(ctx)[0].digest() and len(roster.digest()) == 64
    assert len({roster.digest(), truth.digest(), timeline.digest()}) == 3
    moved = timeline.model_copy(update={"crime_slot": timeline.crime_slot + 1})
    assert moved.digest() != timeline.digest()


def test_outputs_are_frozen_and_reject_unknown_fields():
    roster = stages(GenContext.of(castle(), 2, "short"))[0]
    with pytest.raises(ValidationError):
        roster.scene_type = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        type(roster)(**{**roster.model_dump(), "extra": 1})


def test_a_truth_cannot_name_a_culprit_other_than_s0():
    truth = stages(GenContext.of(castle(), 2, "short"))[1]
    with pytest.raises(ValidationError):
        TruthOut(roster=truth.roster, who_pos="s1")
