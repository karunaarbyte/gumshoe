"""End to end: every stage, then `build_case`, then the real strict validator and simulator.

The evidence design is meant to satisfy the validator by construction (2d-2 spec, sections 3 and
6), so every case must come out with zero issues and no skipped group, at every depth the
preset can use; the negative tests show the harness notices when the design is broken."""

import random
import re

import pytest

from gumshoe.cases.generate import facts as facts_stage
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.facts import DEPTHS, feasible_depths
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Axis, EffectKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.simulate.oracle import judge
from gumshoe.cases.validate.graph import build_graph
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.helpers import replace_fact, replace_record_source
from tests.generate.helpers import (
    PRESET_NAMES,
    SEEDS,
    case_of,
    castle,
    facts_of,
    solution_shape,
)

CLOSED_FORM = {"short": [0, 1], "standard": [0, 1, 2], "long": [2]}  # the castle (spec section 6)


def depths_for(ctx: GenContext) -> list[int]:
    """Every depth the preset can use for this seed's roster."""
    _, _, drawn = facts_of(ctx)
    located = sum(s.subject_type == "location" for s in drawn.record_sources)
    return feasible_depths(ctx.spec, located)


ACTIONS = {0: {3}, 1: {4}, 2: {4, 5}}  # the cheapest solution's sources (spec section 6)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_skeleton_case_passes_the_strict_validator(preset):
    """Zero issues, and the cheapest solution has the shape the depth promises: a case whose
    gates went missing is a valid case of a shallower depth, which only the shape shows."""
    pack = castle()
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        for depth in depths_for(ctx):
            case = case_of(ctx, depth)
            size, deepest, actions = solution_shape(case)
            assert (size, deepest) == (4 + depth, max(1, depth)), (preset, seed, depth)
            assert actions in ACTIONS[depth], (preset, seed, depth, actions)
            report = validate(case, pack, Profile.STRICT)
            assert report.issues == () and report.skipped_groups == (), (
                preset,
                seed,
                depth,
                sorted(report.codes()),
                report.skipped_groups,
            )


def test_the_closed_form_is_exactly_the_set_of_depths_that_validate(monkeypatch):
    """Force every depth past the closed form: the depths it keeps validate, the others fail
    the validator (a window or the source capacity) or cannot even be placed."""
    pack = castle()
    monkeypatch.setattr(facts_stage, "feasible_depths", lambda spec, located: list(DEPTHS))
    for preset in PRESET_NAMES:
        clean = set()
        for depth in DEPTHS:
            outcomes = set()
            for seed in range(15):
                try:
                    case = case_of(GenContext.of(pack, seed, preset), depth)
                except GenerationError:
                    outcomes.add(False)
                    continue
                outcomes.add(validate(case, pack, Profile.STRICT).issues == ())
            assert len(outcomes) == 1, (preset, depth)  # a depth works always or never
            if outcomes == {True}:
                clean.add(depth)
        assert sorted(clean) == CLOSED_FORM[preset]
    monkeypatch.undo()
    for preset in PRESET_NAMES:
        assert depths_for(GenContext.of(pack, 0, preset)) == CLOSED_FORM[preset]


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_simulator_agrees(preset):
    pack = castle()
    for seed in range(10):
        verdict = judge(case_of(GenContext.of(pack, seed, preset)))
        assert set(verdict.decidable_axes) == set(Axis), (preset, seed)
        assert verdict.single_survivor and verdict.can_win, (preset, seed)


def rename_facts(case: Case, rng: random.Random) -> Case:
    """The same case with every fact id replaced by a random one (contract (g))."""
    old = [f.id for f in case.facts]
    new = dict(zip(old, rng.sample([f"f{i:03d}" for i in range(1000)], len(old)), strict=True))

    def ids(values: tuple[str, ...]) -> list[str]:
        return [new[v] for v in values]

    data = case.model_dump(mode="json")
    for fact in data["facts"]:
        fact["id"] = new[fact["id"]]
        fact["requires"], fact["exposed_by"] = ids(fact["requires"]), ids(fact["exposed_by"])
    for suspect in data["suspects"]:
        suspect["secret_fact"] = new[suspect["secret_fact"]]
        suspect["requires"], suspect["knows"] = ids(suspect["requires"]), ids(suspect["knows"])
    for source in data["record_sources"]:
        source["requires"] = ids(source["requires"])
    for location in data["locations"]:
        location["requires"] = ids(location["requires"])
    data["start"]["facts"] = ids(data["start"]["facts"])
    return Case.model_validate(data)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_the_verdict_does_not_depend_on_the_fact_ids(preset):
    """Route tie-breaks use sorted fact ids, and 2d-3 reassigns every id: every minimum-size
    solution must fit the windows, so renaming the facts changes nothing (contract (g))."""
    pack = castle()
    for seed in range(20):
        ctx = GenContext.of(pack, seed, preset)
        for depth in depths_for(ctx):
            case = case_of(ctx, depth)
            shape = solution_shape(case)
            for k in range(3):
                renamed = rename_facts(case, random.Random(f"{seed}/{depth}/{k}"))
                assert validate(renamed, pack, Profile.STRICT).issues == (), (preset, seed, depth)
                assert solution_shape(renamed) == shape, (preset, seed, depth)


def owner(fact_id: str) -> str | None:
    """Whose fact this is, by the neutral id contract: `<prefix>_s<k>` belongs to s<k>, except
    the keys, which say nothing about their suspect (they only open them)."""
    prefix, _, pos = fact_id.partition("_")
    return pos if re.fullmatch(r"s\d+", pos) and prefix != "c" else None


def check_symmetry(case: Case) -> None:
    """Equal by construction (spec section 8): five facts and one lie per suspect, one shape per
    axis, and every candidate's decisive facts at the same depth."""
    counts = {s.id: 0 for s in case.suspects}
    for f in case.facts:
        if (who := owner(f.id)) is not None:
            counts[who] += 1
    assert set(counts.values()) == {5}, counts
    assert sorted(f.speaker or "" for f in case.facts if not f.truthful) == sorted(counts)
    ix = CaseIndex.of(case)
    graph = build_graph(ix)
    for axis in Axis:
        shapes, depths = set(), set()
        for cand in ix.candidates[axis]:
            mine = [
                (f, e)
                for f in case.facts
                if f.truthful
                for e in f.effects
                if e.axis is axis and e.candidate == cand
            ]
            shapes.add(  # decisive or not, never which polarity: that is the deduction
                tuple(sorted((f.source.kind.value, e.kind is EffectKind.SUPPORTS) for f, e in mine))
            )
            decisive = [graph.depth[f.id] for f, e in mine if e.kind is not EffectKind.SUPPORTS]
            assert decisive, (axis, cand)
            depths.add(min(decisive))
        assert len(shapes) == 1 and len(depths) == 1, (axis, shapes, depths)


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_what_a_player_can_observe_is_the_same_for_every_candidate(preset):
    pack = castle()
    for seed in range(40):
        check_symmetry(case_of(GenContext.of(pack, seed, preset)))


# Negative tests: the harness fails when the design is broken.


def standard_case(depth: int) -> tuple[Case, Pack]:
    pack = castle()
    return case_of(GenContext.of(pack, 3, "standard" if depth < 2 else "long"), depth), pack


def test_an_incriminating_item_that_only_supports_is_caught():
    case, pack = standard_case(0)
    item = next(f for f in case.facts if f.id == "x_s0")
    weak = (item.effects[0].model_copy(update={"kind": EffectKind.SUPPORTS}),)
    codes = validate(replace_fact(case, "x_s0", effects=weak), pack, Profile.STRICT).codes()
    assert {"NO_POSITIVE_EVIDENCE", "SHAPE_MISMATCH"} <= codes


def test_a_trace_found_without_its_clue_is_caught():
    case, pack = standard_case(0)
    codes = validate(replace_fact(case, "h_m0", requires=()), pack, Profile.STRICT).codes()
    assert {"ACTIONS_RANGE", "SOLUTION_SIZE_RANGE"} <= codes


@pytest.mark.parametrize("depth", [1, 2])
def test_a_record_gated_by_another_suspects_hint_is_caught(depth):
    case, pack = standard_case(depth)
    culprit = next(r for r in case.record_sources if r.subject == "s0")
    crossed = replace_record_source(case, culprit.kind, "s0", requires=("y_s1",))
    assert "SINGLE_POINT_OF_FAILURE" in validate(crossed, pack, Profile.STRICT).codes()


def test_a_record_gated_by_its_own_suspects_lie_is_caught():
    case, pack = standard_case(1)
    record = next(r for r in case.record_sources if r.subject == "s1")
    own = replace_record_source(case, record.kind, "s1", requires=("l_s1",))
    assert "GATE_ON_OWN_LIE" in validate(own, pack, Profile.STRICT).codes()


def test_the_symmetry_check_can_fail():
    case, _ = standard_case(0)
    second = "x_s1" if any(f.id == "x_s1" for f in case.facts) else "w_s1"
    lopsided = case.model_copy(update={"facts": tuple(f for f in case.facts if f.id != second)})
    with pytest.raises(AssertionError):
        check_symmetry(lopsided)
