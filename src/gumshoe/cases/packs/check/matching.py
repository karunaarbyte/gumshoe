"""Stage 7: suspect-to-motive matching (spec 4.11). Exact and deterministic: it enumerates the
matchings of every roster, so there is no sampling. A roster is a set of distinct roles."""

from collections import Counter
from collections.abc import Iterator, Mapping
from itertools import combinations

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PresetDef
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.check.capacity import hosted_specs
from gumshoe.cases.packs.issues import PackIssue

MAX_SHARE_PERCENT = 50


def matchings(
    allowed: Mapping[str, tuple[str, ...]], roster: tuple[str, ...]
) -> Iterator[tuple[str, ...]]:
    """Every assignment of a distinct allowed motive type to each roster role, in sorted order."""
    chosen: list[str] = []

    def go(i: int) -> Iterator[tuple[str, ...]]:
        if i == len(roster):
            yield tuple(chosen)
            return
        for motive in allowed[roster[i]]:
            if motive not in chosen:
                chosen.append(motive)
                yield from go(i + 1)
                chosen.pop()

    yield from go(0)


def check(pack: Pack, presets: Mapping[str, PresetDef]) -> list[PackIssue]:
    sizes = sorted({spec.suspects for _, spec in hosted_specs(pack, presets) if spec.suspects > 0})
    allowed = {r.key: tuple(sorted(set(r.motive_types))) for r in pack.roles}
    out: list[PackIssue] = []
    for size in sizes:
        for roster in combinations(sorted(allowed), size):
            counts: Counter[tuple[str, str]] = Counter()
            total = 0
            for assignment in matchings(allowed, roster):
                total += 1
                counts.update(zip(roster, assignment, strict=True))
            label = ",".join(roster)
            if total == 0:
                out.append(make("NO_PERFECT_MATCHING", "roles", roster=label))
                continue
            for (role, motive), count in sorted(counts.items()):
                if count * 100 > MAX_SHARE_PERCENT * total:
                    out.append(
                        make(
                            "MOTIVE_TOO_PREDICTABLE",
                            f"roles.{role}.motive_types[{motive}]",
                            roster=label,
                            percent=count * 100 // total,
                        )
                    )
    return out
