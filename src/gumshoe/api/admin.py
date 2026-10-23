"""The operator's access to the stats and decisions: one bearer token from the environment."""

import hmac
import logging

from fastapi import Request

from gumshoe.api.errors import ApiError
from gumshoe.api.ratelimit import request_ip

logger = logging.getLogger(__name__)


class AdminToken(bytes):
    """The token's bytes, with a repr that never shows them (the app state is repr'd in
    tracebacks and debuggers)."""

    def __repr__(self) -> str:
        return "AdminToken(**********)"

    __str__ = __repr__


def admin_token_of(secret: str) -> AdminToken | None:
    """The configured token, or None when it is empty (admin off)."""
    return AdminToken(secret.encode()) if secret else None


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Not Found")


def require_admin(request: Request) -> None:
    """Pass only with the right `Authorization: Bearer <token>`. Everything else, including too
    many failures from one address, is the plain 404 an unknown route gets, so a probe cannot
    tell the admin routes exist. Every refusal is logged once with the address only: never the
    header, the token or the query."""
    token: bytes | None = request.app.state.admin_token
    if token is None:
        raise _not_found()
    ip = request_ip(request)
    quotas = request.app.state.quotas
    if not quotas.admin_blocked(ip):
        header = request.headers.get("authorization", "")
        scheme, _, given = header.partition(" ")
        # Starlette decodes header bytes as latin-1, so any value is a str and encodes cleanly.
        # No strip: "Bearer  <token>" (two spaces) is malformed, and so refused.
        if scheme.lower() == "bearer" and hmac.compare_digest(given.encode(), token):
            return
        quotas.admin_failed(ip)
    logger.info("admin refused ip=%s", ip)
    raise _not_found()
