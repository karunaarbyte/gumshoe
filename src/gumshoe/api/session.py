"""Anonymous sessions: a signed random id in an HttpOnly cookie.

A session is created only when a game is created or loaded. The id says who owns what; it grants
nothing else. The cookie value is `<id>.<signature>`: the signature is an HMAC of the id, so a
client cannot invent or alter an id. Two keys come from the one secret (cookie signing and save
ownership) so one can never be replayed as the other.
"""

import hashlib
import hmac
import logging
import re
import secrets
from typing import Annotated

from fastapi import Depends, Request, Response

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import UNKNOWN_GAME
from gumshoe.config import Settings

logger = logging.getLogger(__name__)

COOKIE_MAX_AGE_S = 30 * 24 * 3600
_ID = re.compile(r"[A-Za-z0-9_-]{22}")  # token_urlsafe(16)
_SIG = re.compile(r"[0-9a-f]{64}")


def _derive(secret: bytes, label: bytes) -> bytes:
    return hmac.new(secret, b"gumshoe/" + label, hashlib.sha256).digest()


class Sessions:
    def __init__(self, secret: bytes, *, secure: bool) -> None:
        self._cookie_key = _derive(secret, b"cookie")
        self._owner_key = _derive(secret, b"save-owner")
        self.secure = secure
        self.cookie_name = "__Host-gs_session" if secure else "gs_session"

    @classmethod
    def from_settings(cls, settings: Settings) -> "Sessions":
        secret = settings.session_secret.get_secret_value().encode()
        if not secret:
            secret = secrets.token_bytes(32)
            logger.warning(
                "SESSION_SECRET is not set: sessions and save ownership reset on every restart"
            )
        return cls(secret, secure=settings.public_mode)

    def _signature(self, session_id: str) -> str:
        return hmac.new(self._cookie_key, session_id.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> tuple[str, str]:
        """A new session: its id and the cookie value to send."""
        session_id = secrets.token_urlsafe(16)
        return session_id, f"{session_id}.{self._signature(session_id)}"

    def read(self, value: str | None) -> str | None:
        """The session id in a cookie value, or None for anything that is not a valid one."""
        if not value or len(value) > 200 or value.count(".") != 1:
            return None
        session_id, signature = value.split(".")
        if not _ID.fullmatch(session_id) or not _SIG.fullmatch(signature):
            return None
        expected = self._signature(session_id)
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            return None
        return session_id

    def owner_tag(self, session_id: str) -> str:
        """A keyed hash of the id, safe to write beside a save (the id itself never is)."""
        return hmac.new(self._owner_key, session_id.encode(), hashlib.sha256).hexdigest()[:32]

    def set_cookie(self, response: Response, value: str) -> None:
        response.set_cookie(
            self.cookie_name,
            value,
            max_age=COOKIE_MAX_AGE_S,
            path="/",
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )


def sessions_of(request: Request) -> Sessions:
    sessions: Sessions = request.app.state.sessions
    return sessions


def current_owner(request: Request) -> str:
    """The caller's session id; with no valid session, the answer a missing game gets."""
    sessions = sessions_of(request)
    session_id = sessions.read(request.cookies.get(sessions.cookie_name))
    if not session_id:  # None or empty: no session
        raise ToolFailure("unknown_game", UNKNOWN_GAME)
    return session_id


def issue_owner(request: Request, response: Response) -> str:
    """The caller's session id, issuing a session (and its cookie) when there is none."""
    sessions = sessions_of(request)
    session_id = sessions.read(request.cookies.get(sessions.cookie_name))
    if not session_id:
        session_id, value = sessions.issue()
        sessions.set_cookie(response, value)
    return session_id


def optional_owner(request: Request) -> str | None:
    """The caller's session id, or None: for the one route where no session is not an error."""
    sessions = sessions_of(request)
    return sessions.read(request.cookies.get(sessions.cookie_name)) or None


Owner = Annotated[str, Depends(current_owner)]
NewOwner = Annotated[str, Depends(issue_owner)]
