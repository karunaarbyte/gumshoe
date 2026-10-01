"""Opt-in tests that call the real backends. Run with: uv run pytest -m live"""

import pytest

from gumshoe.config import Settings
from gumshoe.decider import make_decider
from gumshoe.decider.tools.samples import DEMO_QUESTIONS, DEMO_STATE

pytestmark = pytest.mark.live

HAS_JEV_KEY = bool(Settings().jev_api_key.get_secret_value())


async def _check(backend: str) -> None:
    decider = make_decider(Settings(), backend=backend)
    try:
        result = await decider.decide(DEMO_STATE, DEMO_QUESTIONS, node="live-test")
    finally:
        await decider.aclose()
    assert result.choice("intent").choice in {"action", "dialogue", "accusation", "meta"}
    assert 0.0 <= result.noul("needs_interrogation").noul <= 1.0
    assert result.score("urgency").legend


async def test_nimble_live():
    await _check("nimble")


@pytest.mark.skipif(not HAS_JEV_KEY, reason="JEV_API_KEY not set")
async def test_jev_live():
    await _check("jev")
