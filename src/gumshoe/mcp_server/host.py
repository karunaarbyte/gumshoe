"""GameHost: the games, behind one lock. Every public method returns a play view.

Nothing here imports the `mcp` SDK, so tests and the agent loop use it directly. The SDK runs sync
tools on a worker thread, so every public method holds `self._lock` for its whole body. One lock
means `new_game` (about 0.1 s of generation) pauses every other game; that is fine for one operator.
"""

import secrets
import threading
from collections.abc import Callable
from typing import Protocol

from gumshoe.cases import (
    AccusationPlan,
    AccusationResult,
    AxisOptions,
    BuiltinPackError,
    CaseGenerationError,
    GameNotOver,
    GameOver,
    GameSession,
    HandleCollision,
    NotebookView,
    Pack,
    ParsedAccusation,
    PlayerCaseView,
    RevealView,
    SourceResult,
    UnsupportedPreset,
    View,
    dump_case,
    generate_case,
    load_builtin_pack,
    load_session,
)
from gumshoe.mcp_server.errors import GameError

MAX_SEED = 2**63 - 1
SALT_TRIES = 16
AXES = ("who", "how", "why")


class IdSource(Protocol):
    """Where ids, salts and save names come from: 16 lowercase hex characters per call."""

    def next(self) -> str: ...


class RandomIds:
    def next(self) -> str:
        return secrets.token_hex(8)


class NewGame(View):
    game: str
    brief: PlayerCaseView


class _Game:
    def __init__(self, session: GameSession, case_bytes: bytes, pack: str) -> None:
        self.session = session
        self.case_bytes = case_bytes
        self.pack = pack


def _ended[T](call: Callable[[], T]) -> T:
    """Run an engine call; a finished game becomes `game_over`, a running one `not_over`."""
    try:
        return call()
    except GameOver as exc:
        raise GameError("game_over", "the game has ended") from exc
    except GameNotOver as exc:
        raise GameError("not_over", "the game is still being played") from exc


class GameHost:
    def __init__(self, ids: IdSource | None = None) -> None:
        self._ids: IdSource = ids or RandomIds()
        self._lock = threading.RLock()
        self._games: dict[str, _Game] = {}
        self._packs: dict[str, Pack] = {}

    def _pack(self, name: str) -> Pack:
        if name not in self._packs:
            try:
                self._packs[name] = load_builtin_pack(name)
            except BuiltinPackError as exc:
                raise GameError("bad_argument", f"no pack named {name!r}") from exc
        return self._packs[name]

    def _open(self, case_bytes: bytes) -> GameSession:
        """A session under a fresh salt (a rare handle collision draws the next salt)."""
        for _ in range(SALT_TRIES):
            try:
                return load_session(case_bytes, self._ids.next())
            except HandleCollision:
                continue
        raise RuntimeError("no salt gave collision-free handles")

    def _game(self, game: str) -> _Game:
        found = self._games.get(game)
        if found is None:
            raise GameError("unknown_game", "no such game")
        return found

    def new_game(self, seed: int, preset: str = "standard", pack: str = "castle") -> NewGame:
        if type(seed) is not int or not 0 <= seed <= MAX_SEED:
            raise GameError("bad_argument", f"seed must be an int from 0 to {MAX_SEED}")
        with self._lock:
            the_pack = self._pack(pack)
            try:
                case = generate_case(seed, preset, the_pack)
            except UnsupportedPreset as exc:
                raise GameError("bad_argument", f"the {pack} pack cannot host {preset!r}") from exc
            except CaseGenerationError as exc:
                raise GameError("bad_argument", "no case could be made from this seed") from exc
            case_bytes = dump_case(case)
            session = self._open(case_bytes)
            game_id = self._ids.next()
            self._games[game_id] = _Game(session, case_bytes, pack)
            return NewGame(game=game_id, brief=session.brief())

    def case_brief(self, game: str) -> PlayerCaseView:
        with self._lock:
            return self._game(game).session.brief()

    def search(self, game: str, location: str) -> SourceResult:
        with self._lock:
            session = self._game(game).session
            return _ended(lambda: session.search(location))

    def interrogate(self, game: str, suspect: str) -> SourceResult:
        with self._lock:
            session = self._game(game).session
            return _ended(lambda: session.interrogate(suspect))

    def check_records(self, game: str, subject: str, kind: str | None = None) -> SourceResult:
        with self._lock:
            session = self._game(game).session
            return _ended(lambda: session.check_records(subject, kind))

    def notebook(self, game: str) -> NotebookView:
        with self._lock:
            return self._game(game).session.notebook()

    def give_up(self, game: str) -> RevealView:
        with self._lock:
            session = self._game(game).session
            _ended(session.give_up)
            return _ended(session.reveal)

    def reveal(self, game: str) -> RevealView:
        with self._lock:
            session = self._game(game).session
            return _ended(session.reveal)

    def nameable(self, game: str, axis: str) -> AxisOptions:
        if axis not in AXES:
            raise GameError("bad_argument", f"axis must be one of {', '.join(AXES)}")
        with self._lock:
            return self._game(game).session.nameable(axis)

    def describe_accusation(
        self, game: str, who: str | None = None, how: str | None = None, why: str | None = None
    ) -> AccusationPlan:
        with self._lock:
            session = self._game(game).session
            return session.describe_accusation(ParsedAccusation(who=who, how=how, why=why))

    def accuse(
        self, game: str, who: str, how: str, why: str, confirmed: bool = False
    ) -> AccusationResult:
        with self._lock:
            session = self._game(game).session
            parsed = ParsedAccusation(who=who, how=how, why=why)
            return _ended(lambda: session.accuse(parsed, confirmed=confirmed))
