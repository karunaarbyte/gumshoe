"""The one error the host raises. The code is part of the wire contract (see `tools`)."""

CODES = (
    "unknown_game",
    "unknown_handle",
    "bad_argument",
    "game_over",
    "not_over",
    "state_mismatch",
    "bad_save",
)


class GameError(Exception):
    """A tool call that cannot be answered. `code` is one of `CODES`; `message` is for the agent."""

    def __init__(self, code: str, message: str) -> None:
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
