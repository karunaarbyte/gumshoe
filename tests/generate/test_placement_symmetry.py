"""Nothing about where facts are placed may single out the culprit or the true method.

Each test is a trivial classifier: given what a player can see (which location holds which fact),
pick the suspect or method that a feature points to, and check the hit rate stays within chance
plus three standard deviations. The classifiers are the ones that beat chance when placement
visits suspects in a fixed order or ties break towards the first candidate."""

import random
from collections import Counter
from functools import cache
from math import sqrt

import pytest

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import FactsOut, PlacementOut, TruthOut
from tests.generate.helpers import castle, placement_of

SEEDS = range(1500)
DEPTH_FOR = {"short": 1, "standard": 2, "long": 2}  # the deepest feasible depth: keys at 2


def within_chance(hits: int, trials: int, chance: float) -> bool:
    sigma = sqrt(chance * (1 - chance) / trials)
    return hits / trials <= chance + 3 * sigma


@cache
def cases(preset: str) -> list[tuple[TruthOut, FactsOut, PlacementOut]]:
    """Placement for every seed at the preset's deepest depth, computed once per preset."""
    pack = castle()
    found = []
    for seed in SEEDS:
        ctx = GenContext.of(pack, seed, preset)
        truth, _, facts, placed = placement_of(ctx, DEPTH_FOR[preset])
        found.append((truth, facts, placed))
    return found


def run(preset: str, pick):
    """The hit rate of `pick(truth, facts, placed, rng)` and the average chance of a random pick.

    `pick` returns the position it chose, the true position and how many options there were."""
    hits = 0
    chances = 0.0
    for seed, (truth, facts, placed) in zip(SEEDS, cases(preset), strict=True):
        chosen, truth_pos, options = pick(truth, facts, placed, random.Random(seed))
        hits += chosen == truth_pos
        chances += 1 / options
    return hits, chances / len(SEEDS)


def key_locations(facts, placed):
    where = {p.fact: p.location for p in placed.search}
    return {f.id[2:]: where[f.id] for f in facts.facts if f.id.startswith("c_")}


def pick_suspect_with_the_emptiest_key_location(truth, facts, placed, rng):
    keys = key_locations(facts, placed)
    load = Counter(p.location for p in placed.search)
    fewest = min(load[loc] for loc in keys.values())
    return rng.choice([k for k, loc in keys.items() if load[loc] == fewest]), "s0", len(keys)


def pick_suspect_whose_key_shares_a_location(truth, facts, placed, rng):
    keys = key_locations(facts, placed)
    shared = Counter(keys.values())
    sharing = [k for k, loc in keys.items() if shared[loc] > 1] or list(keys)
    return rng.choice(sharing), "s0", len(keys)


def pick_method_whose_trace_has_the_emptiest_location(truth, facts, placed, rng):
    where = {p.fact: p.location for p in placed.search}
    load = Counter(p.location for p in placed.search)
    traces = {f.id[2:]: where[f.id] for f in facts.facts if f.id.startswith("h_")}
    fewest = min(load[loc] for loc in traces.values())
    return rng.choice([m for m, loc in traces.items() if load[loc] == fewest]), "m0", len(traces)


def pick_method_whose_trace_is_at_the_scene(truth, facts, placed, rng):
    where = {p.fact: p.location for p in placed.search}
    traces = {f.id[2:]: where[f.id] for f in facts.facts if f.id.startswith("h_")}
    at_scene = [m for m, loc in traces.items() if loc == "l0"] or list(traces)
    return rng.choice(at_scene), "m0", len(traces)


def pick_method_whose_clue_is_at_the_scene(truth, facts, placed, rng):
    where = {p.fact: p.location for p in placed.search}
    clues = {f.id[2:]: where[f.id] for f in facts.facts if f.id.startswith("p_")}
    at_scene = [m for m, loc in clues.items() if loc == "l0"] or list(clues)
    return rng.choice(at_scene), "m0", len(clues)


@pytest.mark.parametrize("preset", ["standard", "long"])
@pytest.mark.parametrize(
    "pick", [pick_suspect_with_the_emptiest_key_location, pick_suspect_whose_key_shares_a_location]
)
def test_the_culprit_is_not_betrayed_by_where_the_keys_are(preset, pick):
    hits, chance = run(preset, pick)
    assert within_chance(hits, len(SEEDS), chance), (
        preset,
        pick.__name__,
        hits / len(SEEDS),
        chance,
    )


@pytest.mark.parametrize("preset", ["short", "standard", "long"])
@pytest.mark.parametrize(
    "pick",
    [
        pick_method_whose_trace_has_the_emptiest_location,
        pick_method_whose_trace_is_at_the_scene,
        pick_method_whose_clue_is_at_the_scene,
    ],
)
def test_the_true_method_is_not_betrayed_by_where_its_facts_are(preset, pick):
    hits, chance = run(preset, pick)
    assert within_chance(hits, len(SEEDS), chance), (
        preset,
        pick.__name__,
        hits / len(SEEDS),
        chance,
    )


def test_the_bound_can_fail():
    assert not within_chance(430, 1000, 0.2)  # a classifier at 0.43 against a chance of 0.20
    assert within_chance(210, 1000, 0.2)
