import pytest

from gumshoe.config import Settings
from gumshoe.decider import ShadowDecider
from gumshoe.decider.backends.client import SystemOneClient
from gumshoe.decider.backends.factory import build_profile, make_decider
from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import DeciderConfigError
from tests.decider.fakes import FakeRecorder


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


@pytest.mark.parametrize("raw", ["  k123\n", "k123\r\n", "\tk123 "])
def test_pasted_key_whitespace_is_stripped(raw):
    profile = build_profile(Settings(_env_file=None, jev_api_key=raw), "jev")
    assert profile.api_key == "k123"


def test_whitespace_only_key_counts_as_missing():
    with pytest.raises(DeciderConfigError, match="JEV_API_KEY"):
        build_profile(Settings(_env_file=None, jev_api_key=" \n"), "jev")


def test_without_a_recorder_make_decider_is_a_plain_client():
    settings = Settings(_env_file=None, jev_api_key="k")
    assert isinstance(make_decider(settings), SystemOneClient)


def test_with_a_recorder_and_a_shadow_it_returns_a_shadow_decider():
    settings = Settings(_env_file=None, jev_api_key="k")  # primary jev, shadow nimble
    decider = make_decider(settings, recorder=FakeRecorder())
    assert isinstance(decider, ShadowDecider)
    assert decider.name == "jev"


def test_with_a_recorder_and_no_shadow_it_still_records_the_primary():
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow=None)
    decider = make_decider(settings, recorder=FakeRecorder())
    assert isinstance(decider, ShadowDecider) and decider.name == "nimble"


def test_an_explicit_backend_override_runs_alone():
    settings = Settings(_env_file=None, jev_api_key="k")
    decider = make_decider(settings, backend="nimble", recorder=FakeRecorder())
    assert isinstance(decider, ShadowDecider) and decider.name == "nimble"


def test_a_misconfigured_primary_fails_fast_even_with_a_recorder():
    with pytest.raises(DeciderConfigError, match="JEV_API_KEY"):
        make_decider(Settings(_env_file=None), recorder=FakeRecorder())  # primary jev, no key


def test_a_misconfigured_shadow_fails_fast_too():
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow="jev")
    with pytest.raises(DeciderConfigError, match="JEV_API_KEY"):
        make_decider(settings, recorder=FakeRecorder())


def test_the_cold_threshold_comes_from_settings():
    settings = Settings(_env_file=None, jev_api_key="k", cold_after_s=42)
    decider = make_decider(settings, recorder=FakeRecorder())
    assert isinstance(decider, ShadowDecider)
    assert decider.cold_after_s == 42


def test_no_client_is_built_when_the_shadow_config_is_invalid(monkeypatch):
    built: list[object] = []

    def counting_client(*args, **kwargs):
        client = SystemOneClient(*args, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr("gumshoe.decider.backends.factory.SystemOneClient", counting_client)
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow="jev")  # no key
    with pytest.raises(DeciderConfigError):
        make_decider(settings, recorder=FakeRecorder())
    assert built == []  # the primary client was not created and then abandoned unclosed
