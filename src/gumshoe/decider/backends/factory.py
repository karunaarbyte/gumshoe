"""Builds a Decider for a backend from settings."""

from gumshoe.config import Backend, Settings, get_settings
from gumshoe.decider.backends.client import SystemOneClient
from gumshoe.decider.backends.profile import BackendProfile
from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import DeciderConfigError
from gumshoe.decider.shadow.records import Recorder
from gumshoe.decider.shadow.shadow import ShadowDecider

# On shutdown, a shadow call may still be running: wait as long as a call may take, plus this.
DRAIN_SLACK_S = 5.0


def build_profile(settings: Settings, backend: Backend) -> BackendProfile:
    if backend == "nimble":
        return BackendProfile("nimble", settings.nimble_base_url, settings.nimble_model)
    key = settings.jev_api_key.get_secret_value().strip()  # tolerate pasted newlines/spaces
    if not key:
        raise DeciderConfigError("jev", "JEV_API_KEY is not set (add it to .env)")
    return BackendProfile("jev", settings.jev_base_url, settings.jev_model, api_key=key)


def make_decider(
    settings: Settings | None = None,
    backend: Backend | None = None,
    recorder: Recorder | None = None,
) -> Decider:
    """A Decider for `backend` (default: the configured primary).

    With a recorder, every call is recorded; unless `backend` is given explicitly, the configured
    shadow backend (if any) runs alongside the primary. A misconfigured backend (say a missing Jev
    key) fails here, at construction, not on the first request, and before any client is created.
    """
    settings = settings or get_settings()
    primary_profile = build_profile(settings, backend or settings.decider_primary)
    if recorder is None:
        return _client(settings, primary_profile)
    shadow_backend = settings.decider_shadow if backend is None else None
    shadow_profile = build_profile(settings, shadow_backend) if shadow_backend else None
    shadow = _client(settings, shadow_profile) if shadow_profile else None
    return ShadowDecider(
        _client(settings, primary_profile),
        shadow,
        recorder,
        cold_after_s=settings.cold_after_s,
        drain_grace_s=settings.request_timeout_s + DRAIN_SLACK_S,
        shadow_parallel=settings.shadow_parallel,
    )


def _client(settings: Settings, profile: BackendProfile) -> Decider:
    return SystemOneClient(profile, timeout=settings.request_timeout_s)
