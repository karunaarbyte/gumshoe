"""A cap on request bodies. Uvicorn has none, and the models check sizes only after reading."""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gumshoe.api.errors import error_body

TOO_LARGE = "the request body is too large"


class BodyLimit:
    """Refuse a body over `max_bytes` with 413 `{code: too_large}`: by its Content-Length before
    anything is read, and, for a chunked body (no length), as soon as the bytes read pass the
    cap. The second case raises an HTTPException from inside the read; FastAPI passes that on
    unchanged and the app's HTTP error handler shapes it."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
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

        await self.app(scope, counted, send)
