"""The MCP adapters: one registered tool per `GameHost` method, nothing else.

A `GameError` becomes an SDK `ToolError`, which the SDK reports as an error result whose text is
`Error executing tool <name>: <code>: <message>` (the agent parses the part after the tool name).
Any other exception is a bug: the SDK logs it to stderr and tells the caller only
`Error executing tool <name>`, so no traceback or case detail crosses the wire.
"""

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gumshoe.cases import (
    AccusationPlan,
    AccusationResult,
    AxisOptions,
    NotebookView,
    PersonaBrief,
    PlayerCaseView,
    ReplyCheck,
    RevealView,
    SourceResult,
)
from gumshoe.mcp_server.errors import GameError
from gumshoe.mcp_server.host import GameHost, NewGame
from gumshoe.mcp_server.saves import SaveRef

INSTRUCTIONS = (
    "Play a detective game. Start with new_game(seed), read the brief, then search places, "
    "interrogate suspects and check records to find facts. Every place, suspect and fact is "
    "named by an opaque handle taken from earlier results. Accuse with accuse(who, how, why) "
    "using handles from nameable(axis); the answer says only how many parts were right."
)


def _guarded[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except GameError as exc:
        raise ToolError(str(exc)) from exc


def build_server(host: GameHost) -> MCPServer:
    server = MCPServer("gumshoe", instructions=INSTRUCTIONS)

    def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
        return server.tool()(fn)

    @tool
    def new_game(seed: int, preset: str = "standard", pack: str = "castle") -> NewGame:
        """Start a game on the case for this seed (preset: short, standard or long).
        Returns the game id and the opening brief (places, suspects, record kinds)."""
        return _guarded(lambda: host.new_game(seed, preset, pack))

    @tool
    def case_brief(game: str) -> PlayerCaseView:
        """The opening brief again, with what is locked now and how many attempts are left."""
        return _guarded(lambda: host.case_brief(game))

    @tool
    def search(game: str, location: str) -> SourceResult:
        """Search a place by its handle. status: ok (new facts), nothing_new, locked
        (not reachable yet) or unknown (not a place in this case)."""
        return _guarded(lambda: host.search(game, location))

    @tool
    def interrogate(game: str, suspect: str) -> SourceResult:
        """Question a suspect by handle. Same statuses as search."""
        return _guarded(lambda: host.interrogate(game, suspect))

    @tool
    def check_records(game: str, subject: str, kind: str | None = None) -> SourceResult:
        """Read the records about a suspect or place (handle). kind is a record kind key from
        the brief, or omit it to read every kind about the subject."""
        return _guarded(lambda: host.check_records(game, subject, kind))

    @tool
    def notebook(game: str) -> NotebookView:
        """Everything found so far, grouped by where it was found."""
        return _guarded(lambda: host.notebook(game))

    @tool
    def nameable(game: str, axis: str) -> AxisOptions:
        """The candidates the player may accuse now on axis who, how or why, with a warned flag
        where a rule-out is already held."""
        return _guarded(lambda: host.nameable(game, axis))

    @tool
    def describe_accusation(
        game: str, who: str | None = None, how: str | None = None, why: str | None = None
    ) -> AccusationPlan:
        """Check an accusation without making it: what resolves, what is missing or not yet
        allowed, warnings, and the confirmation line."""
        return _guarded(lambda: host.describe_accusation(game, who, how, why))

    @tool
    def accuse(
        game: str, who: str, how: str, why: str, confirmed: bool = False
    ) -> AccusationResult:
        """Accuse by handles from nameable. Without confirmed=true nothing is spent. With it,
        one attempt is used and only the number of correct parts is returned."""
        return _guarded(lambda: host.accuse(game, who, how, why, confirmed))

    @tool
    def give_up(game: str) -> RevealView:
        """End the game as lost and reveal the truth."""
        return _guarded(lambda: host.give_up(game))

    @tool
    def reveal(game: str) -> RevealView:
        """The truth, once the game is over."""
        return _guarded(lambda: host.reveal(game))

    @tool
    def persona_brief(game: str, suspect: str) -> PersonaBrief:
        """What to say as this suspect: name, traits, speaking style, the statements the player
        has already drawn out of them, and neutral small-talk words. For the agent, not the
        player. Never invent clues beyond `says`."""
        return _guarded(lambda: host.persona_brief(game, suspect))

    @tool
    def check_reply(game: str, suspect: str, player_text: str, reply: str) -> ReplyCheck:
        """Check a drafted in-character reply for words the player has not earned. Returns ok
        and violation categories only."""
        return _guarded(lambda: host.check_reply(game, suspect, player_text, reply))

    @tool
    def save_game(game: str) -> SaveRef:
        """Save the game to disk and return its save name."""
        return _guarded(lambda: host.save_game(game))

    @tool
    def load_game(name: str) -> NewGame:
        """Load a saved game as a new game (new id, new handles)."""
        return _guarded(lambda: host.load_game(name))

    return server
