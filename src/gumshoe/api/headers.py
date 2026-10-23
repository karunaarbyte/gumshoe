"""Security headers on every response, and no-store on answers that set no caching.

Pure ASGI (like `BodyLimit`): only the start message is touched, so a streamed body, the SSE
turn included, goes out chunk by chunk as before.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Scripts, styles, fonts and fetch/SSE all come from the site itself; the inline styles are
# React `style` attributes (the board and the stats bars).
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
)
FIXED = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
}
# One year, this host only: `includeSubDomains` would bind every other site on the domain.
HSTS = "max-age=31536000"


def security_headers(*, hsts: bool) -> dict[str, str]:
    """The headers `SecurityHeaders` adds, for a response that is sent outside it (the 500
    handler runs in Starlette's outermost error middleware)."""
    headers = dict(FIXED)
    if hsts:
        headers["strict-transport-security"] = HSTS
    headers["cache-control"] = "no-store"
    return headers


class SecurityHeaders:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                # MutableHeaders matches names against the raw bytes, so a downstream
                # `Cache-Control` would be missed and a second header appended: lowercase first.
                message["headers"] = [
                    (name.lower(), value) for name, value in message.get("headers", [])
                ]
                headers = MutableHeaders(scope=message)
                for name, value in FIXED.items():
                    headers[name] = value
                if self.hsts:
                    headers["strict-transport-security"] = HSTS
                # Every path, not only /api/: a disabled /docs then looks like any unknown route.
                # The SSE route (no-cache) and the UI files set their own.
                if "cache-control" not in headers:
                    headers["cache-control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
