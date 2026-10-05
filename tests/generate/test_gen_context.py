import pytest

from gumshoe.cases.generate.gen_context import (
    SKELETON_ALGO_VERSION,
    STAGE_VERSIONS,
    STAGES,
    GenContext,
)
from gumshoe.cases.model.spec import PRESETS, UnsupportedPreset, derive_spec
from tests.generate.helpers import PRESET_NAMES, castle


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_context_carries_the_effective_spec_of_the_preset(preset):
    pack = castle()
    ctx = GenContext.of(pack, 5, preset)
    assert ctx.spec == derive_spec(preset, pack, PRESETS)
    assert ctx.seed == 5 and ctx.preset == preset and len(ctx.spec_hash) == 64


def test_the_spec_hash_follows_the_spec_not_the_seed():
    pack = castle()
    assert GenContext.of(pack, 1, "short").spec_hash == GenContext.of(pack, 2, "short").spec_hash
    assert GenContext.of(pack, 1, "short").spec_hash != GenContext.of(pack, 1, "long").spec_hash


def test_an_unknown_preset_is_refused_with_a_clear_message():
    with pytest.raises(UnsupportedPreset, match="epic"):
        GenContext.of(castle(), 1, "epic")


def test_a_preset_the_pack_cannot_host_is_refused_even_when_derive_spec_accepts_it():
    pack = castle()
    two_scenes = pack.model_copy(update={"scene_types": pack.scene_types[:2]})
    assert derive_spec("short", two_scenes, PRESETS).suspects == 4  # derive_spec alone is happy
    with pytest.raises(UnsupportedPreset, match="not hosted"):
        GenContext.of(two_scenes, 1, "short")


def test_streams_are_keyed_by_stage_counter_and_seed():
    pack = castle()
    a, b = GenContext.of(pack, 1, "short"), GenContext.of(pack, 2, "short")
    draw = lambda ctx, stage, n=0: ctx.stream(stage, n).below(10**9)  # noqa: E731
    assert draw(a, "roster") == draw(a, "roster")
    assert len({draw(a, "roster"), draw(a, "truth"), draw(a, "roster", 1), draw(b, "roster")}) == 4


def test_every_stage_has_a_version():
    assert set(STAGE_VERSIONS) == set(STAGES)
    assert set(STAGES) == {"roster", "truth", "timeline", "facts", "placement", "gating"}


@pytest.mark.parametrize("seed", [True, "1", None, 1.5])
def test_a_seed_that_is_not_an_int_is_refused(seed):
    with pytest.raises(TypeError, match="seed must be an int"):
        GenContext.of(castle(), seed, "short")


def test_a_bad_counter_is_refused():
    ctx = GenContext.of(castle(), 1, "short")
    with pytest.raises(ValueError, match="counter"):
        ctx.stream("roster", -1)
    with pytest.raises(TypeError, match="counter must be an int"):
        ctx.stream("roster", True)


def test_a_changed_stage_bumps_its_version_and_the_skeleton_algorithm_version():
    assert STAGE_VERSIONS["roster"] == 2  # 2d-2a: secret kinds chosen with the record-kind set
    assert SKELETON_ALGO_VERSION == 2
