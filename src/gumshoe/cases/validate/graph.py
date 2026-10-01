"""Fact dependency graph: direct deps, ancestor closures, depths, cycles (AND-only gates)."""

from dataclasses import dataclass

from gumshoe.cases.model.index import CaseIndex


@dataclass(frozen=True)
class Graph:
    deps: dict[str, frozenset[str]]  # fact -> direct prerequisites (requires + its source's gate)
    anc: dict[
        str, frozenset[str]
    ]  # fact -> every ancestor (excluding itself); only for acyclic facts
    depth: dict[str, int]  # fact -> longest chain of prerequisites (0 = none)
    cycle: tuple[str, ...]  # facts that sit on, or behind, a cycle (sorted)
    order: tuple[str, ...]  # a topological order of the acyclic facts


def build_graph(index: CaseIndex) -> Graph:
    ids = sorted(index.facts)
    known = set(ids)
    deps = {i: frozenset(d for d in index.deps(index.facts[i]) if d in known) for i in ids}
    remaining = {i: set(d) for i, d in deps.items()}
    dependents: dict[str, list[str]] = {i: [] for i in ids}
    for i, parents in deps.items():
        for parent in parents:
            dependents[parent].append(i)

    queue = [i for i in ids if not remaining[i]]
    order: list[str] = []
    queued = set(queue)
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in sorted(dependents[node]):
            remaining[child].discard(node)
            if not remaining[child] and child not in queued:
                queued.add(child)
                queue.append(child)
    done = set(order)
    cycle = tuple(i for i in ids if i not in done)

    anc: dict[str, frozenset[str]] = {}
    depth: dict[str, int] = {}
    for node in order:
        parents = deps[node]
        gathered: set[str] = set()
        for parent in parents:
            gathered.add(parent)
            gathered |= anc[parent]
        anc[node] = frozenset(gathered)
        depth[node] = 0 if not parents else 1 + max(depth[p] for p in parents)
    return Graph(deps=deps, anc=anc, depth=depth, cycle=cycle, order=tuple(order))
