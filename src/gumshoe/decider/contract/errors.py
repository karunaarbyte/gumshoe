"""Exceptions raised by the decision layer. Messages never contain secrets."""

from collections.abc import Mapping


class DeciderError(Exception):
    def __init__(self, backend: str, message: str) -> None:
        super().__init__(f"[{backend}] {message}")
        self.backend = backend
        self.message = message


class DeciderConfigError(DeciderError):
    """Missing or invalid configuration (e.g. no Jev API key)."""


class DeciderConnectionError(DeciderError):
    """Could not reach the backend (refused, DNS, timeout)."""


class DeciderAPIError(DeciderError):
    """Backend answered with an HTTP error status."""

    def __init__(self, backend: str, status_code: int, body: str) -> None:
        super().__init__(backend, f"HTTP {status_code}: {body[:300]}")
        self.status_code = status_code
        self.body = body


class DeciderParseError(DeciderError):
    """Backend answered 2xx but the body did not match the expected schema."""

    def __init__(self, backend: str, detail: str, raw: str) -> None:
        super().__init__(backend, f"could not parse response: {detail[:300]}")
        self.raw = raw


class DeciderAllFailedError(DeciderError):
    """The primary and the shadow both failed, so there is no result to use."""

    def __init__(self, failures: Mapping[str, DeciderError]) -> None:
        detail = "; ".join(f"{name}: {exc.message}" for name, exc in failures.items())
        super().__init__("+".join(failures), f"all backends failed ({detail})")
        self.failures = dict(failures)


def describe_failure(exc: DeciderError) -> str:
    """A safe description of a failed call: its class, backend and HTTP status, never its text.
    The message may quote a response body, a URL or a key fragment, and may echo the player's
    words, so it must not reach a log line, a stored record or an API response."""
    if isinstance(exc, DeciderAllFailedError):
        parts = ", ".join(f"{name}: {type(e).__name__}" for name, e in exc.failures.items())
        return f"{type(exc).__name__} ({parts})"
    status = f", HTTP {exc.status_code}" if isinstance(exc, DeciderAPIError) else ""
    return f"{type(exc).__name__} ({exc.backend}{status})"
