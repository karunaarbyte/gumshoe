"""A cap on request bodies. Uvicorn has none, and the models check sizes only after reading."""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gumshoe.api.errors import error_body
from gumshoe.api.refusals import log_scope_refusal

TOO_LARGE = "the request body is too large"


class BodyLimit:
    """Refuse a body over `max_bytes` with 413 `{code: too_large}`: by its Content-Length before
    anything is read, and, for a chunked body (no length), as soon as the bytes read pass the
    cap. The second case raises an HTTPException from inside the read; FastAPI passes that on
    unchanged and the app's HTTP error handler shapes it."""

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        *,
        trust_proxy: bool = False,
        cookie_name: str = "gs_session",
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.trust_proxy = trust_proxy  # these two are for the refusal's log line only
        self.cookie_name = cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            log_scope_refusal(
                "too_large", scope, trust_proxy=self.trust_proxy, cookie_name=self.cookie_name
            )
            response = JSONResponse(error_body("too_large", TOO_LARGE), status_code=413)
            await response(scope, receive, send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise HTTPException(413, TOO_LARGE)
            return message

        await self.app(scope, counted, send)  # a chunked 413 is logged by the app's handler
