"""GameHost: the games, behind one lock.

Every public method returns a play view or a `View` the host made (`NewGame`, `SaveRef`).

Nothing here imports the `mcp` SDK, so tests and the agent loop use it directly. The SDK runs sync
tools on a worker thread, so every public method holds `self._lock` for its whole body. One lock
means `new_game` (about 0.1 s of generation) pauses every other game; that is fine for one operator.
"""

import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from gumshoe.cases import (
    AccusationPlan,
    AccusationQuestions,
    AccusationResult,
    AxisOptions,
    BadAnswers,
    BuiltinPackError,
    Case,
    CaseGenerationError,
    GameNotOver,
    GameOver,
    GameSession,
    HandleCollision,
    NoAccusationPrompt,
    NotebookView,
    Pack,
    ParsedAccusation,
    PersonaBrief,
    PlayerCaseView,
    ReplyCheck,
    RevealView,
    SourceResult,
    StateMismatch,
    UnknownHandle,
    UnsupportedPreset,
    VersionMismatch,
    View,
    dump_case,
    generate_case,
    load_builtin_pack,
    load_case,
    load_session,
    regenerate_case,
)
from gumshoe.mcp_server.errors import GameError
from gumshoe.mcp_server.saves import (
    SAVE_FORMAT,
    SaveExists,
    SaveFile,
    SaveRef,
    check_name,
    default_saves_dir,
    path_for,
    read_save,
    write_save,
)

MAX_SEED = 2**63 - 1
SALT_TRIES = 16
MAX_TEXT = 4000
MAX_GAMES = 1000
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


class CloseRef(View):
    closed: str


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


def _require_regenerated(case: Case, case_bytes: bytes, pack: Pack) -> None:
    """A save's case must be exactly what its seed and stage counters rebuild, byte for byte.

    The stored skin hash is no protection on its own (anyone can recompute it), so this is what
    keeps hand-written text out of the agent's context. The host only ever saves generated
    cases. A case this code or pack version cannot rebuild gets its own message."""
    if case.origin.value != "generated":  # an early refusal, not the sole gate
        raise GameError("bad_save", "that save does not hold a sound case")
    try:
        rebuilt = regenerate_case(case, pack)
    except (VersionMismatch, CaseGenerationError) as exc:
        raise GameError(
            "bad_save", "that save was made by another version of the game and cannot be loaded"
        ) from exc
    except ValueError as exc:  # a preset or a stage counter no generator could have stored
        raise GameError("bad_save", "that save does not hold a sound case") from exc
    except Exception as exc:  # a crafted save is a trust boundary: nothing may escape raw
        raise GameError("bad_save", "that save does not hold a sound case") from exc
    if dump_case(rebuilt.model_copy(update={"attempt": case.attempt})) != case_bytes:
        raise GameError("bad_save", "that save does not hold a sound case")


def _check_length(name: str, text: str) -> None:
    if len(text) > MAX_TEXT:
        raise GameError("bad_argument", f"{name} is longer than {MAX_TEXT} characters")


class GameHost:
    def __init__(self, ids: IdSource | None = None, saves_dir: Path | None = None) -> None:
        self._ids: IdSource = ids or RandomIds()
        self._saves_dir = saves_dir
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

    def _open(self, case_bytes: bytes, pack: Pack, state_json: str | None = None) -> GameSession:
        """A session under a fresh salt (a rare handle collision draws the next salt)."""
        for _ in range(SALT_TRIES):
            try:
                return load_session(case_bytes, self._ids.next(), state_json, pack=pack)
            except HandleCollision:
                continue
        raise RuntimeError("no salt gave collision-free handles")

    def _folder(self) -> Path:
        return self._saves_dir if self._saves_dir is not None else default_saves_dir()

    def _fresh_name(self, folder: Path) -> str:
        for _ in range(SALT_TRIES):
            name = self._ids.next()
            check_name(name)
            if not path_for(folder, name).exists():
                return name
        raise RuntimeError("no unused save name")

    def _fresh_game_id(self) -> str:
        if len(self._games) >= MAX_GAMES:
            raise GameError("too_many_games", f"{MAX_GAMES} games are open; close_game one first")
        for _ in range(SALT_TRIES):
            game_id = self._ids.next()
            if game_id not in self._games:
                return game_id
        raise RuntimeError("no unused game id")

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
            session = self._open(case_bytes, the_pack)
            game_id = self._fresh_game_id()
            self._games[game_id] = _Game(session, case_bytes, pack)
            return NewGame(game=game_id, brief=session.brief())

    def close_game(self, game: str) -> CloseRef:
        """Forget a game (its saves stay). The id and its handles stop working."""
        with self._lock:
            self._game(game)
            del self._games[game]
            return CloseRef(closed=game)

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

    def persona_brief(self, game: str, suspect: str) -> PersonaBrief:
        with self._lock:
            session = self._game(game).session
            try:
                return session.persona_brief(suspect)
            except UnknownHandle as exc:
                raise GameError("unknown_handle", "no such suspect") from exc

    def accusation_questions(self, game: str, text: str) -> AccusationQuestions:
        _check_length("text", text)
        with self._lock:
            return self._game(game).session.accusation_questions(text)

    def interpret_accusation(
        self, game: str, probabilities: dict[str, dict[str, float]]
    ) -> ParsedAccusation:
        with self._lock:
            session = self._game(game).session
            try:
                return session.interpret_probabilities(probabilities)
            except NoAccusationPrompt as exc:
                raise GameError("bad_argument", "call accusation_questions first") from exc
            except BadAnswers as exc:
                raise GameError("bad_argument", str(exc)) from exc

    def check_reply(self, game: str, suspect: str, player_text: str, reply: str) -> ReplyCheck:
        for name, text in (("player_text", player_text), ("reply", reply)):
            _check_length(name, text)
        with self._lock:
            check = self._game(game).session.check_reply(suspect, player_text, reply)
            if any(v.category == "unknown_suspect" for v in check.violations):
                raise GameError("unknown_handle", "no such suspect")
            return check

    def save_game(self, game: str) -> SaveRef:
        with self._lock:
            found = self._game(game)
            folder = self._folder()
            save = SaveFile(
                save_format=SAVE_FORMAT,
                pack=found.pack,
                case=found.case_bytes.decode("utf-8"),
                state=found.session.state_json(),
            )
            for _ in range(SALT_TRIES):
                name = self._fresh_name(folder)
                try:
                    write_save(folder, name, save)
                except SaveExists:
                    continue  # another process took the name between the check and the write
                return SaveRef(name=name)
            raise RuntimeError("no unused save name")

    def load_game(self, name: str) -> NewGame:
        with self._lock:
            save = read_save(self._folder(), name)
            case_bytes = save.case.encode("utf-8")
            try:
                case = load_case(case_bytes)
                pack = self._pack(save.pack)
                _require_regenerated(case, case_bytes, pack)
                session = self._open(case_bytes, pack, save.state)
            except ValidationError as exc:
                raise GameError("bad_save", "that save cannot be read") from exc
            except StateMismatch as exc:
                raise GameError(
                    "state_mismatch", "that save's progress is for another case"
                ) from exc
            except GameError as exc:
                if exc.code == "bad_argument":
                    raise GameError("bad_save", "that save names a pack this server lacks") from exc
                raise
            game_id = self._fresh_game_id()
            self._games[game_id] = _Game(session, case_bytes, save.pack)
            return NewGame(game=game_id, brief=session.brief())
