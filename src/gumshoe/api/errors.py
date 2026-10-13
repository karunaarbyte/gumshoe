"""How a failure becomes an HTTP answer: a status and a `{code, message}` body."""

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
