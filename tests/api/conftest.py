import pytest

from gumshoe.config import Settings


@pytest.fixture(autouse=True)
def settings_without_a_dotenv(monkeypatch):
    """create_app reads the settings when it is given none; a test must never read the
    developer's .env (it may hold a real Jev key, CORS origins or prices)."""
    monkeypatch.setattr("gumshoe.api.app.get_settings", lambda: Settings(_env_file=None))
