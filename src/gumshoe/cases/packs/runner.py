"""The pack-load pipeline (spec 4.1): stage order and stop rules, one sorted result."""

from collections.abc import Mapping

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef
from gumshoe.cases.packs.check import (
    capacity,
    feasibility,
    hygiene,
    matching,
    plausibility,
    refs,
    skin_inputs,
    templates,
)
from gumshoe.cases.packs.issues import PackIssue


def sorted_issues(issues: list[PackIssue]) -> tuple[PackIssue, ...]:
    return tuple(sorted(issues, key=PackIssue.sort_key))


def check_pack(pack: Pack, presets: Mapping[str, PresetDef] = PRESETS) -> tuple[PackIssue, ...]:
    """Stages 2 to 8 on a pack that already passed the schema stage. Stage 2 errors stop
    everything after (they need resolved references); stages 3, 4, 5 and 8 run together; stages 6
    and 7 run only when stage 5 found nothing."""
    unresolved = refs.check(pack)
    if unresolved:
        return sorted_issues(unresolved)
    found = [*templates.check(pack), *hygiene.check(pack), *skin_inputs.check(pack)]
    plausibility_issues = plausibility.check(pack)
    found += plausibility_issues
    if not plausibility_issues:
        found += capacity.check(pack, presets)
        found += capacity.pool_problems(pack)
        found += matching.check(pack, presets)
        found += feasibility.check(pack, presets)
    return sorted_issues(found)
