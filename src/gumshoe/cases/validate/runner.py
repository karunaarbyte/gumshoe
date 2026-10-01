"""Runs the rule groups in order, skipping those whose prerequisites failed."""

from collections.abc import Callable, Mapping

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.groups import (
    g01_structure,
    g02_labels,
    g03_graph,
    g04_reachability,
    g05_lies,
    g06_solvability,
    g07_timeline,
    g08_difficulty,
    g09_fairness,
    g10_persona,
    g11_pack,
)
from gumshoe.cases.validate.report import Issue, Profile, Report, Severity

RUNNERS: dict[int, Callable[[Ctx], list[Issue]]] = {
    1: g01_structure.run,
    2: g02_labels.run,
    3: g03_graph.run,
    4: g04_reachability.run,
    5: g05_lies.run,
    6: g06_solvability.run,
    7: g07_timeline.run,
    8: g08_difficulty.run,
    9: g09_fairness.run,
    10: g10_persona.run,
    11: g11_pack.run,
}

REQUIRES: dict[int, frozenset[int]] = {
    1: frozenset(),
    2: frozenset({1}),
    3: frozenset({1}),
    4: frozenset({1, 3}),
    5: frozenset({1, 3}),  # lies compute reachability themselves (unreachable exposers)
    6: frozenset({1, 3, 4}),
    7: frozenset({1}),
    8: frozenset({1, 3, 4, 6}),
    9: frozenset({1, 3, 4}),
    10: frozenset({1, 3}),
    11: frozenset({1}),
}


def validate(
    case: Case,
    pack: Pack | None = None,
    profile: Profile = Profile.STRICT,
    presets: Mapping[str, PresetDef] = PRESETS,
) -> Report:
    """Never raises on bad content: every issue (sorted) plus the skipped groups."""
    ctx = Ctx(case=case, pack=pack, profile=profile, presets=dict(presets))
    blocking: set[int] = set()
    skipped: list[int] = []
    issues: list[Issue] = []
    for group in sorted(REQUIRES):
        if REQUIRES[group] & blocking:
            skipped.append(group)
            blocking.add(group)  # skipping propagates to groups that depend on this one
            continue
        run = RUNNERS.get(group)
        if run is None:
            continue
        try:
            found = run(ctx)
        except Exception as exc:  # noqa: BLE001  a crashing rule must not take the validator down
            found = [ctx.issue("INTERNAL_ERROR", str(group), error=type(exc).__name__)]
        issues.extend(found)
        if any(issue.severity is Severity.ERROR for issue in found):
            blocking.add(group)
    ordered = tuple(sorted(issues, key=lambda issue: issue.sort_key()))
    return Report(profile=profile, issues=ordered, skipped_groups=tuple(skipped))
