"""Opt-in tests that call the real backends. Run with: uv run pytest -m live

These read your real .env on purpose, and only when they actually run (never at import time,
so a broken .env can't break collection of the normal suite).
"""

import pytest

from gumshoe.config import Settings
from gumshoe.decider import make_decider
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE

pytestmark = pytest.mark.live


@pytest.fixture
def live_settings(monkeypatch) -> Settings:
    # Settings() reads the real .env from the working directory. The autouse fixture in
    # conftest cleared the process environment, so only .env values apply here.
    return Settings()


async def _check(settings: Settings, backend: str) -> None:
    decider = make_decider(settings, backend=backend)
    try:
        result = await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="live-test")
    finally:
        await decider.aclose()
    assert result.choice("intent").choice in {"action", "dialogue", "accusation", "meta"}
    assert 0.0 <= result.noul("needs_interrogation").noul <= 1.0
    assert result.score("urgency").legend


async def test_nimble_live(live_settings):
    await _check(live_settings, "nimble")


async def test_jev_live(live_settings):
    if not live_settings.jev_api_key.get_secret_value():
        pytest.skip("JEV_API_KEY not set")
    await _check(live_settings, "jev")
