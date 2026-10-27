"""Stages 6 and 7: whether each claimed preset can be built from the pack. The helpers here
are the roster rules the generator also uses, and the roster walk visits every draw the
generator's roster stage could make (stage 7)."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from itertools import combinations

from gumshoe.cases.model.entities import Spec
from gumshoe.cases.model.pack import MethodDef, Pack, RecordDef, SceneType
from gumshoe.cases.model.spec import PresetDef
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.capacity import (
    eligible_roles,
    hosted_specs,
    hosting_scenes,
    usable_kind,
)
from gumshoe.cases.packs.check.depths import feasible_depths
from gumshoe.cases.packs.issues import PackIssue

# The walk's work for one preset, in units: one per draw, per visited record-kind subset and
# per location-subset check. A preset whose walk would do more is unsupported here, which
# keeps the load bounded.
ROSTER_CHECK_BUDGET = 1_000_000
MAX_ROSTER_FAILURES = 5  # reported per preset
NO_RECORD_SET = "no record-kind set gives every role a kind and every kind a holder"
NO_PLACES = "no set of locations satisfies the trace and record constraints"


def holder_assignments(kinds: list[str], options: list[list[str]]) -> Iterator[dict[int, str]]:
    """Every way to give each kind its own holder: a distinct role index whose options list it."""
    held: dict[int, str] = {}

    def go() -> Iterator[dict[int, str]]:
        if len(held) == len(kinds):
            yield dict(held)
            return
        kind = kinds[len(held)]  # one kind is placed per level, so the level is len(held)
        for role, opts in enumerate(options):
            if role not in held and kind in opts:
                held[role] = kind
                yield from go()
                del held[role]

    yield from go()


def trace_ok(method: MethodDef, scene: SceneType, places: set[str]) -> bool:
    """Some trace of the method fits the scene's trace kinds and a non-scene chosen place."""
    return any(
        t.kind in scene.allowed_trace_kinds and places & set(t.location_kinds)
        for t in method.traces
    )


def reachable_location_records(pack: Pack, record_kinds: int) -> range:
    """How many of a case's record kinds can be location-subject, given the pack's kinds."""
    suspect = sum(1 for d in pack.record_defs if d.subject == "suspect")
    place = sum(1 for d in pack.record_defs if d.subject == "location")
    return range(max(0, record_kinds - suspect), min(record_kinds, place) + 1)


def no_depth_presets(pack: Pack, presets: Mapping[str, PresetDef]) -> set[str]:
    """Names of the claimed presets for which no record-kind count leaves a feasible depth."""
    out: set[str] = set()
    for name, spec in hosted_specs(pack, presets):
        counts = reachable_location_records(pack, spec.record_kinds)
        if not any(feasible_depths(spec, n) for n in counts):
            out.add(name)
    return out


@dataclass
class WalkResult:
    # one per (scene, roles, record-kind subset with holders, methods); the budget counts more
    # (every work unit, see ROSTER_CHECK_BUDGET), so `draws` never reaches it alone
    draws: int = 0
    failures: list[str] = field(default_factory=list)  # distinct reasons, at most the cap
    over_budget: bool = False


class _OverBudget(Exception):
    pass


@dataclass(frozen=True)
class _RecordDraw:
    kinds: tuple[str, ...]  # the chosen record kinds, sorted
    secrets: tuple[str, ...]  # the suspects' secret record kinds: the suspect-subject ones


class _Walk:
    """One preset's walk: the pack's lookups, the work counter and the found failures."""

    def __init__(self, pack: Pack, spec: Spec, budget: int) -> None:
        self.pack, self.spec, self.budget = pack, spec, budget
        self.records = {d.key: d for d in pack.record_defs}
        self.roles = {r.key: r for r in pack.roles}
        self.methods = {m.key: m for m in pack.method_defs}
        # an event-subject record kind has no source in the facts stage, so it is never chosen
        self.choosable = sorted(
            k for k, d in self.records.items() if d.subject in ("suspect", "location")
        )
        self.work = 0
        self.result = WalkResult()
        self.record_draws: dict[tuple[tuple[str, ...], ...], list[_RecordDraw]] = {}
        self.placed: dict[tuple[str, _RecordDraw, tuple[str, ...]], bool] = {}

    def spend(self) -> None:
        self.work += 1
        if self.work > self.budget:
            raise _OverBudget

    def fail(self, reason: str) -> bool:
        """Records a failure; True once the cap is reached and the walk can stop."""
        if reason not in self.result.failures:
            self.result.failures.append(reason)
        return len(self.result.failures) >= MAX_ROSTER_FAILURES

    def draws_for(self, usable: list[list[str]]) -> list[_RecordDraw]:
        """The (record kinds, secret kinds) pairs `_record_kinds_and_secrets` can draw for roles
        with these usable kinds, in sorted order. `usable_kind` admits suspect-subject kinds only
        and every chosen suspect-subject kind has a holder, so the suspects' secret kinds are
        always exactly the subset's suspect-subject kinds: one draw per subset with holders."""
        key = tuple(tuple(opts) for opts in usable)
        if key in self.record_draws:
            return self.record_draws[key]
        found: list[_RecordDraw] = []
        for subset in combinations(self.choosable, self.spec.record_kinds):
            self.spend()  # every visited subset, kept or not: a large pool cannot hang the walk
            chosen = set(subset)
            if any(not chosen & set(opts) for opts in usable):
                continue
            held = tuple(k for k in subset if self.records[k].subject == "suspect")
            if next(holder_assignments(list(held), usable), None) is not None:
                found.append(_RecordDraw(subset, held))
        self.record_draws[key] = found
        return found

    def placeable(self, scene: SceneType, draw: _RecordDraw, method_keys: tuple[str, ...]) -> bool:
        """Whether `location_kinds` has a feasible set: (c) every method has a trace at a chosen
        non-scene place, (b') every secret kind attests a chosen non-scene place, (g') every
        location-subject record kind attests a chosen place or the scene's kind."""
        key = (scene.key, draw, method_keys)
        if key not in self.placed:
            self.placed[key] = self._placeable(scene, draw, method_keys)
        return self.placed[key]

    def _placeable(self, scene: SceneType, draw: _RecordDraw, method_keys: tuple[str, ...]) -> bool:
        scene_kind = scene.location_kinds[0]
        others = sorted({d.key for d in self.pack.location_defs} - {scene_kind})
        methods = [self.methods[k] for k in method_keys]
        secret_places = [set(self.records[k].location_kinds) for k in draw.secrets]
        record_places = [set(r.location_kinds) for r in self._located(draw.kinds)]
        for subset in combinations(others, self.spec.locations - 1):
            self.spend()
            chosen = set(subset)
            if (
                all(trace_ok(m, scene, chosen) for m in methods)
                and all(chosen & places for places in secret_places)
                and all((chosen | {scene_kind}) & places for places in record_places)
            ):
                return True
        return False

    def _located(self, kinds: tuple[str, ...]) -> list[RecordDef]:
        return [self.records[k] for k in kinds if self.records[k].subject == "location"]

    def scene(self, scene: SceneType) -> bool:
        """Walks one scene; True once the failure cap is reached."""
        scene_methods = sorted(set(scene.allowed_methods))
        for role_keys in combinations(eligible_roles(self.pack, scene), self.spec.suspects):
            usable = [
                sorted(
                    k
                    for k in self.roles[key].record_kinds
                    if k in self.records and usable_kind(self.records[k], scene)
                )
                for key in role_keys
            ]
            roster = f"scene {scene.key}, roles {'+'.join(role_keys)}"
            draws = self.draws_for(usable)
            if not draws and self.fail(f"{roster}: {NO_RECORD_SET}"):
                return True
            for draw in draws:
                located = len(self._located(draw.kinds))
                depths = feasible_depths(self.spec, located)
                # lazy: every subset spends before the next is made, so memory follows the budget
                for method_keys in combinations(scene_methods, self.spec.methods):
                    self.result.draws += 1
                    self.spend()
                    if not self.placeable(scene, draw, method_keys):
                        reason = (
                            f"{roster}, record kinds {'+'.join(draw.kinds)}, secret kinds"
                            f" {'+'.join(draw.secrets)}, methods {'+'.join(method_keys)}:"
                            f" {NO_PLACES}"
                        )
                    elif not depths:
                        reason = (
                            f"{roster}, record kinds {'+'.join(draw.kinds)}: no gating depth"
                            f" fits {located} location-subject record kinds"
                        )
                    else:
                        continue
                    if self.fail(reason):
                        return True
        return False


def walk(pack: Pack, spec: Spec, budget: int) -> WalkResult:
    """Every roster draw the generator could make for a preset (its effective `spec`): the
    reasons the roster stage or the depth step would fail on some of them, at most
    MAX_ROSTER_FAILURES, in walk order. Stops with `over_budget` once the work passes `budget`.
    Not modelled: fewer than three locations, and a placement with no room because more
    methods than the source cap fit only one place."""
    state = _Walk(pack, spec, budget)
    try:
        for scene in hosting_scenes(pack, spec):
            if state.scene(scene):
                break
    except _OverBudget:
        state.result.over_budget = True
    return state.result


def check(pack: Pack, presets: Mapping[str, PresetDef]) -> list[PackIssue]:
    """PRESET_NO_DEPTH, then ROSTER_INFEASIBLE or PRESET_UNSUPPORTED for each claimed preset."""
    no_depth = no_depth_presets(pack, presets)
    out = [
        make("PRESET_NO_DEPTH", f"meta.presets[{name}]", preset=name) for name in sorted(no_depth)
    ]
    for name, spec in hosted_specs(pack, presets):
        if name in no_depth:
            continue  # every draw fails at the depth step: PRESET_NO_DEPTH already says so
        path = f"meta.presets[{name}]"
        result = walk(pack, spec, ROSTER_CHECK_BUDGET)
        out += [
            make("ROSTER_INFEASIBLE", path, preset=name, reason=reason)
            for reason in result.failures
        ]
        if result.over_budget:
            reason = f"roster check too large (more than {ROSTER_CHECK_BUDGET} work units)"
            out.append(make("PRESET_UNSUPPORTED", path, reason=reason))
    return out
