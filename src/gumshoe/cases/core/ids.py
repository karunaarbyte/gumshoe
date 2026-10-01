"""Entity id format: short, lowercase, charset-restricted, and (when generated) hash-derived."""

import re

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest

ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,31}")
_PREFIX = re.compile(r"[a-z]{1,3}")


def is_valid_id(value: str) -> bool:
    return ID_PATTERN.fullmatch(value) is not None


def make_id(prefix: str, *parts: object) -> str:
    """`prefix_` + 8 hex digits derived from the parts (never from a list index)."""
    if _PREFIX.fullmatch(prefix) is None:
        raise ValueError(f"bad id prefix: {prefix!r}")
    payload = canonical_json(list(parts))  # typed and unambiguous: 1 != "1", no separator tricks
    return f"{prefix}_{domain_digest('gumshoe.id.v1', payload)[:8]}"
