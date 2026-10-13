"""Opt-in: about five free-text turns against real Jev and Ollama. Run once, at the end:
`uv run pytest -m live tests/api/test_live.py`. Reads the real .env on purpose, and only when it
runs. Hosted Jev is billed per call."""

import pytest

from gumshoe.api.service import AgentService
from gumshoe.api.wiring import default_service
from gumshoe.config import Settings
from gumshoe.stats import SqliteStatsStore

pytestmark = pytest.mark.live

TURNS = [
    "I look around the first place on the list",
    "what have I found so far?",
    "let me question the first suspect",
    "what do the records say about the second suspect?",
    "tell me again what we know",
]


async def play(service: AgentService, game: str, text: str):
    return [event async for event in service.start_turn(game, text)]


async def test_five_free_text_turns_against_real_backends(tmp_path):
    settings = Settings()  # the real .env
    if settings.decider_primary == "jev" and not settings.jev_api_key.get_secret_value():
        pytest.skip("JEV_API_KEY not set")
    store = SqliteStatsStore(tmp_path / "live.db")
    async with default_service(store, settings) as service:
        new = await service.new_game(1)
        transcript = []
        for text in TURNS:
            events = await play(service, new.game, text)
            transcript.append((text, [e.kind for e in events]))
            assert events and events[-1].kind == "done", transcript
            errors = [e for e in events if e.kind == "clarify" and e.reason == "error"]
            assert not errors, f"{text!r} hit an error clarify: {transcript}"
    print(transcript)  # noqa: T201  (shown with -s)
    assert store.fetch_recent(limit=20), "no decisions were recorded"
