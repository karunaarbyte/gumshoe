"""The facts stage: every fact of the case, before any is placed or gated."""

from gumshoe.cases.model.entities import Spec

DEPTHS = (0, 1, 2)  # 0: no gate; 1: records need a hint; 2: suspects also need a key


def feasible_depths(spec: Spec, location_records: int) -> list[int]:
    """The gating depths that fit the preset's windows and the source capacity, in order.

    The cheapest solution of a depth-d case is the incriminating item, the secret and the how
    proof (with its clue), plus the gate chain: size 4 + d, depth max(1, d), and 3 distinct
    sources (the culprit's record and the two search locations), 4 once a hint must be found."""
    limits, cap = spec.limits, spec.source_cap
    suspects, methods, locations = spec.suspects, spec.methods, spec.locations
    found = []
    for d in DEPTHS:
        actions = 3 if d == 0 else 4
        if not (
            limits.solution_min <= 4 + d <= limits.solution_max
            and limits.depth_min <= max(1, d) <= limits.depth_max
            and limits.actions_min <= actions <= limits.actions_max
        ):
            continue
        search = 2 * methods + (suspects if d == 2 else 0)
        records = 3 * suspects + location_records
        record_sources = suspects + location_records
        if (
            search * 5 <= 4 * cap * locations  # the validator's 0.8 x cap x sources rule
            and records * 5 <= 4 * cap * record_sources
            and cap >= 3
        ):
            found.append(d)
    return found
