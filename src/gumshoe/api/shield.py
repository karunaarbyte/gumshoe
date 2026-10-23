"""Refuse state-changing requests that do not come from the site itself (CSRF)."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gumshoe.api.errors import error_body
from gumshoe.api.refusals import log_scope_refusal

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
FORBIDDEN = "this request does not come from the site"
NOT_JSON = "send the body as application/json"


def origin_of(headers: Headers) -> str | None:
    """The request's origin: the Origin header, else the origin part of the Referer."""
    if (origin := headers.get("origin")) is not None:
        return origin
    if (referer := headers.get("referer")) is not None:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return None


def is_json(content_type: str) -> bool:
    """Whether the media type (parameters such as `charset` aside) is exactly application/json,
    in any case."""
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


class OriginCheck:
    """`allowed` are the exact origins accepted. With `local` set (no PUBLIC_ORIGIN) the request's
    own `scheme://Host` is accepted too; in public mode the Host header is never trusted."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed: tuple[str, ...],
        local: bool,
        trust_proxy: bool = False,
        cookie_name: str = "gs_session",
    ) -> None:
        self.app = app
        self.allowed = frozenset(item.lower() for item in allowed)
        self.local = local
        self.trust_proxy = trust_proxy  # these two are for the refusal's log line only
        self.cookie_name = cookie_name

    def _log(self, code: str, scope: Scope) -> None:
        log_scope_refusal(code, scope, trust_proxy=self.trust_proxy, cookie_name=self.cookie_name)

    def _accepts(self, scope: Scope, headers: Headers) -> bool:
        origin = origin_of(headers)
        if origin is None:
            return False
        origin = origin.lower()  # scheme and host are case-insensitive; browsers send lowercase
        if origin in self.allowed:
            return True
        host = headers.get("host")
        return self.local and host is not None and origin == f"{scope['scheme']}://{host}".lower()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not self._accepts(scope, headers):
            self._log("forbidden", scope)
            response = JSONResponse(error_body("forbidden", FORBIDDEN), status_code=403)
            await response(scope, receive, send)
            return
        has_body = headers.get("content-length", "0") != "0" or "transfer-encoding" in headers
        if has_body and not is_json(headers.get("content-type", "")):
            self._log("bad_request", scope)
            response = JSONResponse(error_body("bad_request", NOT_JSON), status_code=415)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
