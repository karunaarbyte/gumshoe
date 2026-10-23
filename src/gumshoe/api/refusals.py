"""One log line per refused request: what was refused, where, and for whom (never what was said).

Every field is made safe before it is written: the path comes from the client, so it is cut to
a length and anything but a visible ASCII character (spaces, newlines, escape codes, other
scripts) becomes `?`, which keeps a crafted path from faking a field or a whole line. The query
string is never part of the route, and of the session cookie only six characters of its id part
are kept (never the signature). On the admin routes the line carries the code and the address
only, like the gate's own `admin refused ip=` line: no route, no session."""

import logging
import re
from contextlib import suppress
from http.cookies import SimpleCookie

from starlette.datastructures import Headers
from starlette.types import Scope

from gumshoe.api.ratelimit import client_ip

logger = logging.getLogger("gumshoe.api.refusals")

# Error codes from the ApiError handler that count as a refusal (an ordinary 404 or 422 does not;
# the admin gate's 404 is `not_found`, so it is never logged twice). The middlewares log their
# own refusals (403 forbidden, 415 bad_request, 413 too_large, 429 rate_limited) directly.
REFUSED = frozenset({"rate_limited", "quota", "busy", "forbidden", "cold", "too_many_games"})

# The routes behind the admin gate (a test checks every gated route is covered).
ADMIN_PREFIXES = ("/api/admin", "/api/stats", "/api/decisions")

MAX_FIELD = 200
_UNSAFE = re.compile(r"[^\x21-\x7e]")
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")


def admin_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in ADMIN_PREFIXES)


def _safe(value: object, limit: int = MAX_FIELD) -> str:
    text = value if isinstance(value, str) else str(value)
    return _UNSAFE.sub("?", text[:limit]) or "-"


def session_prefix(cookie: object) -> str:
    """The first 6 characters of the cookie's id part (`<id>.<signature>`), or `-`."""
    if not isinstance(cookie, str) or len(cookie) > 200 or cookie.count(".") != 1:
        return "-"
    session_id = cookie.split(".")[0]
    return session_id[:6] if _SESSION_ID.fullmatch(session_id) else "-"


def route_of(route: object) -> str:
    """A safe `METHOD path` from `route`, or `-` on an admin route (the path has no query)."""
    method, sep, path = (route if isinstance(route, str) else str(route)).partition(" ")
    if not sep:
        return _safe(method)
    if admin_path(path):
        return "-"
    return f"{_safe(method, 16)} {_safe(path)}"


def log_refusal(code: str, route: str, ip: str, session_cookie: str | None) -> None:
    """Never raises: a broken log must not change the answer."""
    try:
        safe_route = route_of(route)
        session = "-" if safe_route == "-" else session_prefix(session_cookie)
        logger.info(
            "refused code=%s route=%s ip=%s session=%s",
            _safe(code, 32),
            safe_route,
            _safe(ip, 64),
            session,
        )
    except Exception:
        pass


def refusal_context(
    scope: Scope, *, trust_proxy: bool, cookie_name: str
) -> tuple[str, str, str | None]:
    """(route, ip, session cookie) for a refusal decided from the raw ASGI scope."""
    headers = Headers(scope=scope)
    peer = scope["client"][0] if scope.get("client") else None
    ip = client_ip(peer, headers.get("x-forwarded-for"), trust_proxy=trust_proxy)
    cookie: SimpleCookie = SimpleCookie()
    with suppress(Exception):  # a malformed cookie header: no session prefix
        cookie.load(headers.get("cookie", ""))
    morsel = cookie.get(cookie_name)
    route = f"{scope.get('method', '-')} {scope.get('path', '-')}"
    return route, ip, morsel.value if morsel else None


def log_scope_refusal(code: str, scope: Scope, *, trust_proxy: bool, cookie_name: str) -> None:
    """`log_refusal` for a middleware; never raises either."""
    try:
        context = refusal_context(scope, trust_proxy=trust_proxy, cookie_name=cookie_name)
    except Exception:
        return
    log_refusal(code, *context)
