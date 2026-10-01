"""Builds a Decider for a backend from settings."""

from gumshoe.config import Backend, Settings, get_settings
from gumshoe.decider.base import Decider
from gumshoe.decider.client import SystemOneClient
from gumshoe.decider.errors import DeciderConfigError
from gumshoe.decider.profile import BackendProfile


def build_profile(settings: Settings, backend: Backend) -> BackendProfile:
    if backend == "nimble":
        return BackendProfile("nimble", settings.nimble_base_url, settings.nimble_model)
    key = settings.jev_api_key.get_secret_value()
    if not key:
        raise DeciderConfigError("jev", "JEV_API_KEY is not set (add it to .env)")
    return BackendProfile("jev", settings.jev_base_url, settings.jev_model, api_key=key)


def make_decider(settings: Settings | None = None, backend: Backend | None = None) -> Decider:
    settings = settings or get_settings()
    chosen = backend or settings.decider_primary
    return SystemOneClient(build_profile(settings, chosen), timeout=settings.request_timeout_s)
