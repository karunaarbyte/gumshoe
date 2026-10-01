import pytest

from gumshoe.config import Settings
from gumshoe.decider.base import Decider
from gumshoe.decider.client import SystemOneClient
from gumshoe.decider.errors import DeciderConfigError
from gumshoe.decider.factory import build_profile, make_decider


def test_build_nimble_profile():
    profile = build_profile(Settings(_env_file=None), "nimble")
    assert profile.name == "nimble"
    assert profile.base_url == "http://localhost:11434/v1"
    assert profile.model == "nimble"
    assert profile.api_key is None


def test_build_jev_profile_uses_key():
    profile = build_profile(Settings(_env_file=None, jev_api_key="k123"), "jev")
    assert profile.name == "jev"
    assert profile.base_url == "https://api.typesafe.ai/v1"
    assert profile.model == "jev-latest"
    assert profile.api_key == "k123"


def test_jev_without_key_is_a_config_error():
    with pytest.raises(DeciderConfigError, match="JEV_API_KEY"):
        build_profile(Settings(_env_file=None), "jev")


def test_built_profile_does_not_leak_key_in_repr():
    profile = build_profile(Settings(_env_file=None, jev_api_key="s3cret-key"), "jev")
    assert "s3cret-key" not in repr(profile)


def test_make_decider_defaults_to_the_primary_backend():
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow=None)
    decider = make_decider(settings)
    assert decider.name == "nimble"
    assert isinstance(decider, Decider)
    assert isinstance(decider, SystemOneClient)


def test_make_decider_backend_override():
    settings = Settings(_env_file=None, jev_api_key="k")
    assert make_decider(settings, backend="nimble").name == "nimble"
    assert make_decider(settings, backend="jev").name == "jev"
