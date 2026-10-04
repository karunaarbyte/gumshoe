from collections import Counter, defaultdict

import pytest

from gumshoe.cases.generate.gen_context import GenContext
from tests.generate.helpers import (
    PRESET_NAMES,
    SEEDS,
    castle,
    chi2_critical,
    chi2_statistic,
    truth_of,
)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_truth_is_s0_m0_v0_and_nothing_else_changes(preset):
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        before, truth = truth_of(ctx)
        after = truth.roster
        assert (truth.who_pos, truth.how_pos, truth.why_pos) == ("s0", "m0", "v0")
        assert after.suspects[0].pos == "s0" and after.suspects[0].motive_pos == "v0"
        for group, prefix in (("suspects", "s"), ("methods", "m"), ("motives", "v")):
            assert [x.pos for x in getattr(after, group)] == [
                f"{prefix}{i}" for i in range(len(getattr(after, group)))
            ]
        # the same people, methods and motives: only positions changed, each suspect kept its motive
        key = lambda r: {  # noqa: E731
            s.name: (s.role, s.record_kind, next(m.key for m in r.motives if m.pos == s.motive_pos))
            for s in r.suspects
        }
        assert key(before) == key(after)
        assert {m.key for m in before.methods} == {m.key for m in after.methods}
        assert after.scene_type == before.scene_type and after.locations == before.locations
        assert after.record_kinds == before.record_kinds


def test_the_culprit_is_the_suspect_the_truth_stream_drew():
    ctx = GenContext.of(castle(), 9, "standard")
    before, truth = truth_of(ctx)
    stream = ctx.stream("truth")
    culprit, method = stream.below(len(before.suspects)), stream.below(len(before.methods))
    assert truth.roster.suspects[0].name == before.suspects[culprit].name
    assert truth.roster.methods[0].key == before.methods[method].key


def culprit_statistics(preset: str) -> tuple[float, int, float, int]:
    """(role, motive) goodness of fit and pre-reorder position uniformity over the seeds."""
    pack = castle()
    expected: dict[object, float] = defaultdict(float)
    observed: Counter[object] = Counter()
    position: Counter[int] = Counter()
    size = 0
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        before, truth = truth_of(ctx)
        size = len(before.suspects)
        for s in before.suspects:
            motive = next(m.key for m in before.motives if m.pos == s.motive_pos)
            expected[(s.role, motive)] += 1 / size
        c = truth.roster.suspects[0]
        observed[(c.role, next(m.key for m in truth.roster.motives if m.pos == c.motive_pos))] += 1
        position[[s.name for s in before.suspects].index(c.name)] += 1
    cells = [cell for cell, e in expected.items() if e >= 5]
    cell_stat = chi2_statistic(dict(observed), expected)
    flat = {i: position[i] for i in range(size)}
    pos_stat = chi2_statistic(flat, {i: len(SEEDS) / size for i in range(size)})
    return cell_stat, len(cells), pos_stat, size


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_culprits_role_motive_pair_and_position_fit_the_uniform_draw(preset):
    cell_stat, cells, pos_stat, size = culprit_statistics(preset)
    assert cells >= 15  # enough cells with an expected count of at least 5 to mean something
    assert cell_stat < chi2_critical(cells), (preset, cell_stat)
    assert pos_stat < chi2_critical(size - 1), (preset, pos_stat)


def test_the_statistic_catches_a_culprit_that_is_not_uniform():
    biased = {i: 200 if i == 0 else 0 for i in range(4)}
    assert chi2_statistic(biased, {i: 50.0 for i in range(4)}) > chi2_critical(3)
