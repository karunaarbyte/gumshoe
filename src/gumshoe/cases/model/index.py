"""Read-only lookup tables over a case. Tolerates garbled input: the validator builds it first."""

from dataclasses import dataclass

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Event,
    Fact,
    Location,
    Method,
    Motive,
    RecordSource,
    SourceRef,
    Suspect,
)
from gumshoe.cases.model.enums import Axis, SourceKind


@dataclass(frozen=True)
class CaseIndex:
    case: Case
    facts: dict[str, Fact]
    suspects: dict[str, Suspect]
    locations: dict[str, Location]
    methods: dict[str, Method]
    motives: dict[str, Motive]
    events: dict[str, Event]
    record_sources: dict[tuple[str, str], RecordSource]
    candidates: dict[Axis, tuple[str, ...]]

    @staticmethod
    def of(case: Case) -> "CaseIndex":
        return CaseIndex(
            case=case,
            facts={f.id: f for f in case.facts},
            suspects={s.id: s for s in case.suspects},
            locations={loc.id: loc for loc in case.locations},
            methods={m.id: m for m in case.methods},
            motives={m.id: m for m in case.motives},
            events={e.id: e for e in case.timeline},
            record_sources={(r.kind, r.subject): r for r in case.record_sources},
            candidates={
                Axis.WHO: tuple(s.id for s in case.suspects),
                Axis.HOW: tuple(m.id for m in case.methods),
                Axis.WHY: tuple(m.id for m in case.motives),
            },
        )

    def truth(self, axis: Axis) -> str:
        return {
            Axis.WHO: self.case.truth.who,
            Axis.HOW: self.case.truth.how,
            Axis.WHY: self.case.truth.why,
        }[axis]

    def source_gate(self, source: SourceRef) -> tuple[str, ...]:
        """The facts that must be discovered before this source can be used."""
        if source.kind is SourceKind.SEARCH:
            loc = self.locations.get(source.target)
            return loc.requires if loc else ()
        if source.kind is SourceKind.INTERROGATE:
            sus = self.suspects.get(source.target)
            return sus.requires if sus else ()
        rs = self.record_sources.get((source.target, source.subject or ""))
        return rs.requires if rs else ()

    def facts_at(self, source: SourceRef) -> tuple[Fact, ...]:
        return tuple(f for f in self.case.facts if f.source == source)

    def deps(self, fact: Fact) -> frozenset[str]:
        """Direct prerequisites: the fact's own `requires` plus its source's gate."""
        return frozenset(fact.requires) | frozenset(self.source_gate(fact.source))
