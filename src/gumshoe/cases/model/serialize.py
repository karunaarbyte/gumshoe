"""Canonical dump/load and the two hashes: the skeleton digest and the skin hash."""

from enum import Enum
from typing import Any

from pydantic import BaseModel

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.roles import FIELD_ROLES, FieldRole


def dump_case(case: Case) -> bytes:
    """Every field (skeleton, skin and meta), as canonical JSON."""
    return canonical_json(case.model_dump(mode="json"))


def load_case(data: bytes) -> Case:
    return Case.model_validate_json(data)


def _value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _walk(value)
    if isinstance(value, tuple | list):
        return [_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _walk(model: BaseModel) -> dict[str, Any]:
    """Skeleton fields only (nested models are skeleton throughout, so the walk recurses)."""
    roles = FIELD_ROLES[type(model).__name__]
    return {
        name: _value(getattr(model, name))
        for name in type(model).model_fields
        if roles[name] is FieldRole.SKELETON
    }


def _skin_of(value: Any) -> Any:
    """The skin inside a value, however deeply nested; None when there is none."""
    if isinstance(value, BaseModel):
        roles = FIELD_ROLES[type(value).__name__]
        out: dict[str, Any] = {}
        for name in type(value).model_fields:
            attr = getattr(value, name)
            if roles[name] is FieldRole.SKIN:
                out[name] = _value(attr)
            else:
                nested = _skin_of(attr)
                if nested is not None:
                    out[name] = nested
        if out and roles.get("id") is FieldRole.SKELETON:
            out["id"] = dict(value)["id"]
        return out or None
    if isinstance(value, tuple | list):
        items = [item for item in (_skin_of(v) for v in value) if item is not None]
        return items or None
    return None


def skeleton_dict(case: Case) -> dict[str, Any]:
    return _walk(case)


def skin_dict(case: Case) -> dict[str, Any]:
    """Skin fields only, with entity ids as keys so edits stay attributable."""
    return _skin_of(case) or {}


def skeleton_digest(case: Case) -> str:
    return domain_digest("gumshoe.case.skeleton.v1", canonical_json(skeleton_dict(case)))


def skin_hash(case: Case) -> str:
    return domain_digest("gumshoe.case.skin.v1", canonical_json(skin_dict(case)))
