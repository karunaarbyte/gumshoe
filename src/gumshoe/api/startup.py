"""Settings that are legal but probably wrong, reported once at startup.

Messages name settings only, never their values.
"""

from gumshoe.config import Settings

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def startup_warnings(settings: Settings, bind_host: str) -> list[str]:
    warnings: list[str] = []
    loopback = bind_host in LOOPBACK
    if (settings.public_mode or not loopback) and not settings.trust_proxy:
        warnings.append(
            "TRUST_PROXY is false: every visitor will be seen as one client (the proxy's address), "
            "so the per-IP limits apply to all of them together. Set TRUST_PROXY=true behind "
            "exactly one trusted proxy such as a tunnel."
        )
    if settings.trust_proxy and not loopback:
        warnings.append(
            f"TRUST_PROXY is true but the server listens on {bind_host}: anyone who can reach it "
            "directly can send a forged X-Forwarded-For. Bind to 127.0.0.1 behind the proxy."
        )
    return warnings
