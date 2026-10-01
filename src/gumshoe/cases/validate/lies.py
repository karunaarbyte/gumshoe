"""The shared definition of a valid exposer."""

from gumshoe.cases.model.entities import Fact, SourceRef
from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.validate.graph import Graph


def exposer_problem(
    index: CaseIndex, graph: Graph, reach_facts: frozenset[str], lie: Fact, exposer: Fact
) -> str | None:
    """Why this fact cannot expose this lie, or None if it can."""
    if not exposer.truthful:
        return "EXPOSER_IS_LIE"
    if lie.speaker is not None and exposer.source == SourceRef(
        kind=SourceKind.INTERROGATE, target=lie.speaker
    ):
        return "EXPOSER_OWNED_BY_SPEAKER"
    if lie.id in graph.anc.get(exposer.id, frozenset()):
        return "EXPOSER_DEPENDS_ON_LIE"
    if exposer.id not in reach_facts:
        return "EXPOSER_UNREACHABLE"
    return None


def valid_exposers(
    index: CaseIndex, graph: Graph, reach_facts: frozenset[str], lie: Fact
) -> list[Fact]:
    found: list[Fact] = []
    for exposer_id in lie.exposed_by:
        exposer = index.facts.get(exposer_id)
        if exposer is not None and exposer_problem(index, graph, reach_facts, lie, exposer) is None:
            found.append(exposer)
    return found
