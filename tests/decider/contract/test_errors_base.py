import pytest

from gumshoe.decider.contract.base import Decider
from gumshoe.decider.contract.errors import (
    DeciderAllFailedError,
    DeciderAPIError,
    DeciderConfigError,
    DeciderConnectionError,
    DeciderError,
    DeciderParseError,
)
from tests.decider.fakes import FakeDecider


def test_all_errors_share_a_base():
    for exc in (
        DeciderConfigError("jev", "x"),
        DeciderConnectionError("jev", "x"),
        DeciderAPIError("jev", 500, "boom"),
        DeciderParseError("jev", "bad", "<html>"),
    ):
        assert isinstance(exc, DeciderError)
        assert exc.backend == "jev"
        assert str(exc).startswith("[jev] ")


def test_api_error_keeps_status_and_truncates_message_but_not_body():
    body = "x" * 1000
    exc = DeciderAPIError("nimble", 404, body)
    assert exc.status_code == 404
    assert exc.body == body
    assert "404" in str(exc)
    assert len(str(exc)) < 400


def test_parse_error_keeps_raw_body():
    exc = DeciderParseError("nimble", "not json", "<html>oops</html>")
    assert exc.raw == "<html>oops</html>"


def test_fake_satisfies_decider_protocol_without_inheriting():
    # FakeDecider never imports or subclasses Decider: the match is structural.
    assert isinstance(FakeDecider("fake"), Decider)
    assert Decider not in FakeDecider.__mro__


def test_errors_can_chain():
    try:
        try:
            raise ValueError("low level")
        except ValueError as inner:
            raise DeciderParseError("jev", "bad", "raw") from inner
    except DeciderParseError as outer:
        assert isinstance(outer.__cause__, ValueError)
    with pytest.raises(DeciderError):
        raise DeciderConfigError("jev", "missing key")


def test_all_failed_error_lists_every_backend_failure():
    failures = {
        "jev": DeciderConnectionError("jev", "cannot reach"),
        "nimble": DeciderAPIError("nimble", 404, "model not found"),
    }
    exc = DeciderAllFailedError(failures)
    assert isinstance(exc, DeciderError)
    assert exc.failures == failures
    assert exc.backend == "jev+nimble"
    assert "cannot reach" in str(exc) and "model not found" in str(exc)
