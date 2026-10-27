"""The roster walk of the pack checks against the generator's roster stage and depth step.

`generate_case` retries a failed draw under a new counter, which hides a stage that can fail,
so the stage is called directly. The walk visits every draw the stage could make; the seeds
sample those draws, so each variant here fails on many draws or on none.
"""

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef, SizeRange
from gumshoe.cases.packs.check.capacity import hosted_specs
from gumshoe.cases.packs.check.depths import feasible_depths
from gumshoe.cases.packs.check.feasibility import ROSTER_CHECK_BUDGET, walk
from tests.generate.helpers import PRESET_NAMES, castle, castle_with, roster_of

CROSS_SEEDS = range(300)
Change = Callable[[dict[str, Any]], None]


def _trace(method: str, kinds: list[str]) -> Change:
    def change(data: dict[str, Any]) -> None:
        (m,) = [m for m in data["method_defs"] if m["key"] == method]
        m["traces"][0]["location_kinds"] = kinds

    return change


def _record(key: str, **fields: Any) -> Change:
    def change(data: dict[str, Any]) -> None:
        (r,) = [r for r in data["record_defs"] if r["key"] == key]
        r.update(fields)

    return change


def _all(*changes: Change) -> Change:
    def change(data: dict[str, Any]) -> None:
        for c in changes:
            c(data)

    return change


VARIANTS: dict[str, Change] = {
    # (g'): a gatehouse murder with the gate log is placed by the scene's own kind
    "castle": lambda data: None,
    # (c): a chapel murder by dagger has no non-scene place for the wound
    "dagger only in the chapel": _trace("dagger", ["chapel"]),
    "rope only in the herb garden": _trace("rope", ["herb_garden"]),
    # (b'): the secret kinds must attest a chosen non-scene place, not the scene itself
    "secret kinds narrowed": _all(
        _trace("crossbow", ["kitchen"]),
        _record("chapel_register", location_kinds=["great_hall", "undercroft"]),
        _record("visitor_ledger", location_kinds=["chapel", "herb_garden"]),
    ),
    # every record kind is about a suspect: some rosters have no holder for every kind
    "gate log about a suspect": _record("gate_log", subject="suspect"),
}


def _stage_fails(pack: Pack, preset: str, presets: Mapping[str, PresetDef] = PRESETS) -> bool:
    """Whether some seed's roster stage, or the depth step of the facts stage, fails."""
    records = {d.key: d for d in pack.record_defs}
    for seed in CROSS_SEEDS:
        ctx = GenContext.of(pack, seed, preset, presets)
        try:
            roster = roster_of(ctx)
        except GenerationError:
            return True
        located = sum(records[k].subject == "location" for k in roster.record_kinds)
        if not feasible_depths(ctx.spec, located):
            return True
    return False


def _walk_fails(pack: Pack, preset: str, presets: Mapping[str, PresetDef] = PRESETS) -> bool:
    spec = dict(hosted_specs(pack, presets))[preset]
    result = walk(pack, preset, spec, ROSTER_CHECK_BUDGET)
    assert not result.over_budget
    return bool(result.failures)


def test_the_castle_has_no_failing_seed_and_no_walk_failure():
    pack = castle()
    for preset in PRESET_NAMES:
        assert not _stage_fails(pack, preset), preset
        assert not _walk_fails(pack, preset), preset


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_the_walk_fails_exactly_when_some_seed_of_the_stage_fails(variant):
    pack = castle_with(VARIANTS[variant])
    hosted = dict(hosted_specs(pack, PRESETS))  # a narrowed variant may lose a preset
    verdicts = {
        p: (_walk_fails(pack, p), _stage_fails(pack, p)) for p in PRESET_NAMES if p in hosted
    }
    assert verdicts, "the variant hosts no preset"
    assert all(walked == staged for walked, staged in verdicts.values()), verdicts
    if variant != "castle":
        assert any(staged for _, staged in verdicts.values()), "the variant fails nowhere"


def test_the_walk_finds_a_record_kind_set_with_no_depth_as_the_facts_stage_does():
    # three suspects and methods at a 12% decisive share leave depth 2 only, and only with the
    # location-subject gate log among the record kinds
    short = PRESETS["short"]
    three = SizeRange(min=3, max=3)
    tight = short.model_copy(
        update={
            "suspects": three,
            "methods": three,
            "limits": short.limits.model_copy(update={"decisive_pct_max": 12}),
        }
    )
    presets = {**PRESETS, "short": tight}
    pack = castle()
    assert _walk_fails(pack, "short", presets) and _stage_fails(pack, "short", presets)
