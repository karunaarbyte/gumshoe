"""Canonical JSON: one byte string per value, independent of dict order and Python version."""

import json
import unicodedata
from enum import Enum
from typing import Any


def _normalise(value: Any) -> Any:
    if isinstance(value, Enum):
        return _normalise(value.value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not allowed in canonical JSON")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normal_key = unicodedata.normalize("NFC", key)
            if normal_key in result:
                raise TypeError(f"canonical JSON keys collide after normalisation: {normal_key!r}")
            result[normal_key] = _normalise(item)
        return result
    raise TypeError(f"unsupported type for canonical JSON: {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    """Sorted keys, compact separators, NFC text, no floats, UTF-8 without ASCII escaping."""
    return json.dumps(
        _normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
