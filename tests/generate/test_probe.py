import pytest

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.helpers import replace_in
from tests.generate.helpers import PRESET_NAMES, SEEDS, castle, stages
from tests.generate.probe import probe_case

LATER_STAGES = {
    "EMPTY_LOCATION",
    "NO_STATEMENT",
    "OPPORTUNITY_NOT_RULED_OUT",
    "UNTOUCHABLE_CANDIDATE",
}


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_structural_probe_passes_for_every_seed(preset):
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        _, truth, timeline = stages(ctx)
        report = validate(probe_case(ctx, truth, timeline), pack, Profile.STRICT)
        assert report.skipped_groups == (6, 8, 9), (preset, seed)
        assert report.codes() <= LATER_STAGES, (preset, seed, sorted(report.codes() - LATER_STAGES))


def probe_report(mutate):
    pack = castle()
    ctx = GenContext.of(pack, 4, "standard")
    _, truth, timeline = stages(ctx)
    return validate(mutate(probe_case(ctx, truth, timeline)), pack, Profile.STRICT)


def test_the_probe_fails_when_the_culprit_is_off_the_scene():
    def culprit_elsewhere(case):
        slot = next(e.slot for e in case.timeline if e.action == "crime")
        case = replace_in(case, "timeline", f"e_s0_{slot}", place="l1", action="present")
        return replace_in(case, "timeline", f"e_s1_{slot}", place="l0", action="crime")

    assert "CULPRIT_NO_OPPORTUNITY" in probe_report(culprit_elsewhere).codes()


def test_the_probe_fails_when_a_chosen_record_kind_has_no_source():
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, "short")
        _, truth, timeline = stages(ctx)
        case = probe_case(ctx, truth, timeline)
        stub = next((f for f in case.facts if f.id.startswith("f_stub_")), None)
        if stub is None:
            continue
        without = case.model_copy(
            update={
                "record_sources": tuple(
                    r
                    for r in case.record_sources
                    if (r.kind, r.subject) != (stub.source.target, stub.source.subject)
                ),
                "facts": tuple(f for f in case.facts if f.id != stub.id),
                "start": case.start.model_copy(
                    update={"facts": tuple(f for f in case.start.facts if f != stub.id)}
                ),
            }
        )
        assert validate(without, pack, Profile.STRICT).codes() == {"COUNT_MISMATCH"}
        return
    pytest.fail("no short seed left a record kind to the stub")
