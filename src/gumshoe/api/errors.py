"""How a failure becomes an HTTP answer: a status and a `{code, message}` body."""

from collections.abc import Sequence
from typing import Any

STATUS = {
    "unknown_game": 404,
    "bad_argument": 422,
    "unknown_handle": 422,
    "bad_save": 422,
    "internal": 500,
    "too_many_games": 429,
}
OTHER = 409  # game_over, not_over, state_mismatch and anything new


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def status_for(code: str) -> int:
    return STATUS.get(code, OTHER)


def error_body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


# FastAPI's and Starlette's own errors, in the same `{code, message}` shape
HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "too_large",
    422: "bad_request",
}


def http_code(status: int) -> str:
    return HTTP_CODES.get(status, "http_error")


def describe_validation(errors: Sequence[Any]) -> str:
    """Where and what, for the first few problems. Never the input: it may be the player's text."""
    parts = []
    for error in list(errors)[:3]:
        where = ".".join(str(p) for p in error.get("loc", ()) if p != "body") or "request"
        parts.append(f"{where}: {error.get('msg', 'is not valid')}")
    return "; ".join(parts) or "the request is not valid"
