"""Domain-separated SHA-256."""

import hashlib


def domain_digest(domain: str, payload: bytes) -> str:
    """sha256(domain NUL payload) as lowercase hex; the domain keeps digests apart."""
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + payload).hexdigest()
