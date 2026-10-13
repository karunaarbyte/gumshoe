"""The typed face of the game for the agent: one method per MCP tool the loop uses.

The only agent module that imports the MCP SDK. A tool error arrives as text
`Error executing tool <tool>: <code>: <message>`; it becomes a `ToolFailure` with a known code.
Anything else (an argument-validation message, a bare `Error executing tool x`, a missing
structured result) becomes `ToolFailure("internal", ...)` and is never shown to the player.
"""

import re
from typing import Any

from mcp.client import Client
from pydantic import BaseModel, ConfigDict

from gumshoe.cases import (
    AccusationPlan,
    AccusationQuestions,
    AccusationResult,
    NotebookView,
    ParsedAccusation,
    PersonaBrief,
    PlayerCaseView,
    ReplyCheck,
    RevealView,
    SourceResult,
)

# A copy of gumshoe.mcp_server.errors.CODES (the agent must not import the server);
# tests/agent/test_game.py keeps the two equal.
CODES = (
    "unknown_game",
    "unknown_handle",
    "bad_argument",
    "game_over",
    "not_over",
    "state_mismatch",
    "bad_save",
    "too_many_games",
)
INTERNAL = "internal"
ERROR = re.compile(r"^Error executing tool \w+: (?P<code>[a-z_]+): (?P<message>.+)$", re.DOTALL)


class ToolFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class NewGameView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    game: str
    brief: PlayerCaseView


class SaveView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str


class GameClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.call_tool(tool, arguments)
        if result.is_error:
            text = getattr(result.content[0], "text", "") if result.content else ""
            match = ERROR.match(text)
            if match is not None and match["code"] in CODES:
                raise ToolFailure(match["code"], match["message"])
            raise ToolFailure(INTERNAL, "the game server failed")
        if result.structured_content is None:
            raise ToolFailure(INTERNAL, "the game server returned no result")
        data: dict[str, Any] = result.structured_content
        return data

    async def new_game(
        self, seed: int, preset: str = "standard", pack: str = "castle"
    ) -> NewGameView:
        data = await self._call("new_game", {"seed": seed, "preset": preset, "pack": pack})
        return NewGameView.model_validate(data)

    async def close_game(self, game: str) -> None:
        await self._call("close_game", {"game": game})

    async def save_game(self, game: str) -> SaveView:
        return SaveView.model_validate(await self._call("save_game", {"game": game}))

    async def load_game(self, name: str) -> NewGameView:
        return NewGameView.model_validate(await self._call("load_game", {"name": name}))

    async def case_brief(self, game: str) -> PlayerCaseView:
        return PlayerCaseView.model_validate(await self._call("case_brief", {"game": game}))

    async def search(self, game: str, location: str) -> SourceResult:
        data = await self._call("search", {"game": game, "location": location})
        return SourceResult.model_validate(data)

    async def interrogate(self, game: str, suspect: str) -> SourceResult:
        data = await self._call("interrogate", {"game": game, "suspect": suspect})
        return SourceResult.model_validate(data)

    async def check_records(self, game: str, subject: str, kind: str | None = None) -> SourceResult:
        args: dict[str, Any] = {"game": game, "subject": subject}
        if kind is not None:
            args["kind"] = kind
        return SourceResult.model_validate(await self._call("check_records", args))

    async def notebook(self, game: str) -> NotebookView:
        return NotebookView.model_validate(await self._call("notebook", {"game": game}))

    async def give_up(self, game: str) -> RevealView:
        return RevealView.model_validate(await self._call("give_up", {"game": game}))

    async def reveal(self, game: str) -> RevealView:
        return RevealView.model_validate(await self._call("reveal", {"game": game}))

    async def persona_brief(self, game: str, suspect: str) -> PersonaBrief:
        data = await self._call("persona_brief", {"game": game, "suspect": suspect})
        return PersonaBrief.model_validate(data)

    async def check_reply(
        self, game: str, suspect: str, player_text: str, reply: str
    ) -> ReplyCheck:
        data = await self._call(
            "check_reply",
            {"game": game, "suspect": suspect, "player_text": player_text, "reply": reply},
        )
        return ReplyCheck.model_validate(data)

    async def describe_accusation(
        self, game: str, who: str | None, how: str | None, why: str | None
    ) -> AccusationPlan:
        args: dict[str, Any] = {"game": game}
        args.update({k: v for k, v in (("who", who), ("how", how), ("why", why)) if v is not None})
        return AccusationPlan.model_validate(await self._call("describe_accusation", args))

    async def accuse(
        self, game: str, who: str, how: str, why: str, confirmed: bool
    ) -> AccusationResult:
        data = await self._call(
            "accuse",
            {"game": game, "who": who, "how": how, "why": why, "confirmed": confirmed},
        )
        return AccusationResult.model_validate(data)

    async def accusation_questions(self, game: str, text: str) -> AccusationQuestions:
        data = await self._call("accusation_questions", {"game": game, "text": text})
        return AccusationQuestions.model_validate(data)

    async def interpret_accusation(
        self, game: str, probabilities: dict[str, dict[str, float]]
    ) -> ParsedAccusation:
        data = await self._call(
            "interpret_accusation", {"game": game, "probabilities": probabilities}
        )
        return ParsedAccusation.model_validate(data)
