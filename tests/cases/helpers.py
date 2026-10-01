"""Typed helpers for deliberately breaking a case (model_copy skips validation on purpose)."""

from typing import Any

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact


def replace_fact(case: Case, fact_id: str, **changes: Any) -> Case:
    facts = tuple(f.model_copy(update=changes) if f.id == fact_id else f for f in case.facts)
    return case.model_copy(update={"facts": facts})


def drop_fact(case: Case, fact_id: str) -> Case:
    return case.model_copy(update={"facts": tuple(f for f in case.facts if f.id != fact_id)})


def add_fact(case: Case, fact: Fact) -> Case:
    return case.model_copy(update={"facts": (*case.facts, fact)})


def replace_in(case: Case, field: str, entity_id: str, **changes: Any) -> Case:
    """Replace fields of the entity with this id in suspects/locations/methods/motives/timeline."""
    items = tuple(
        e.model_copy(update=changes) if e.id == entity_id else e for e in getattr(case, field)
    )
    return case.model_copy(update={field: items})


def drop_in(case: Case, field: str, entity_id: str) -> Case:
    return case.model_copy(
        update={field: tuple(e for e in getattr(case, field) if e.id != entity_id)}
    )


def replace_spec(case: Case, **changes: Any) -> Case:
    return case.model_copy(update={"spec": case.spec.model_copy(update=changes)})


def replace_limits(case: Case, **changes: Any) -> Case:
    limits = case.spec.limits.model_copy(update=changes)
    return case.model_copy(update={"spec": case.spec.model_copy(update={"limits": limits})})


def replace_truth(case: Case, **changes: Any) -> Case:
    return case.model_copy(update={"truth": case.truth.model_copy(update=changes)})


def replace_start(case: Case, **changes: Any) -> Case:
    return case.model_copy(update={"start": case.start.model_copy(update=changes)})


def replace_record_source(case: Case, kind: str, subject: str, **changes: Any) -> Case:
    sources = tuple(
        r.model_copy(update=changes) if (r.kind, r.subject) == (kind, subject) else r
        for r in case.record_sources
    )
    return case.model_copy(update={"record_sources": sources})
