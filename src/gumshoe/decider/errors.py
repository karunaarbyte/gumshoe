"""Exceptions raised by the decision layer. Messages never contain secrets."""


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
