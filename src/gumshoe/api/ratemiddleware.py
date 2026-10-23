"""Per-IP request rate, applied to every request."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gumshoe.api.errors import ApiError, error_body
from gumshoe.api.ratelimit import Quotas, client_ip
from gumshoe.api.refusals import log_scope_refusal


class RequestRate:
    def __init__(
        self, app: ASGIApp, *, quotas: Quotas, trust_proxy: bool, cookie_name: str = "gs_session"
    ) -> None:
        self.app = app
        self.quotas = quotas
        self.trust_proxy = trust_proxy
        self.cookie_name = cookie_name  # for the refusal's log line only

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        peer = scope["client"][0] if scope.get("client") else None
        forwarded = Headers(scope=scope).get("x-forwarded-for")
        ip = client_ip(peer, forwarded, trust_proxy=self.trust_proxy)
        try:
            self.quotas.request(ip)
        except ApiError as exc:
            log_scope_refusal(
                exc.code, scope, trust_proxy=self.trust_proxy, cookie_name=self.cookie_name
            )
            response = JSONResponse(
                error_body(exc.code, exc.message),
                status_code=exc.status,
                headers={"Retry-After": str(exc.retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
