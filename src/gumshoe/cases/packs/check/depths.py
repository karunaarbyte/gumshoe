"""The gating depths a preset can use: the rule the generator and the pack checks share."""

from gumshoe.cases.model.entities import Spec

DEPTHS = (0, 1, 2)  # 0: no gate; 1: records need a hint; 2: suspects also need a key


def feasible_depths(spec: Spec, location_records: int) -> list[int]:
    """The gating depths that fit the preset's windows and the source capacity, in order.

    The cheapest solution of a depth-d case is the incriminating item, the secret and the how
    proof (with its clue), plus the gate chain: size 4 + d, depth max(1, d), and 3 distinct
    sources (the culprit's record and the two search locations), 4 once a hint must be found.
    Depth 2 may need a fifth action (the culprit's key at a third location). Every depth also
    needs the decisive facts (three) to stay within their share of all facts, and no more than
    two locations per method, or placement leaves a location empty."""
    # interrogation capacity (2S facts over S sources) is implied by cap >= 3, so no clause
    limits, cap = spec.limits, spec.source_cap
    suspects, methods, locations = spec.suspects, spec.methods, spec.locations
    found = []
    for d in DEPTHS:
        fewest, most = (3, 3) if d == 0 else (4, 5 if d == 2 else 4)  # actions of the cheapest
        if not (
            limits.solution_min <= 4 + d <= limits.solution_max
            and limits.depth_min <= max(1, d) <= limits.depth_max
            and limits.actions_min <= fewest
            and most <= limits.actions_max
        ):
            continue
        total = 5 * suspects + 2 * methods + location_records + (suspects if d == 2 else 0)
        if limits.decisive_pct_max * total < 300 or locations > 2 * methods:
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
