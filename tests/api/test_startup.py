import logging

from pydantic import SecretStr

import gumshoe.api.__main__ as entry
from gumshoe.api.startup import startup_warnings
from gumshoe.config import Settings


def s(**kw):
    return Settings(_env_file=None, **kw)


def public(**kw):
    return s(public_origin="https://g.example.com", session_secret=SecretStr("s" * 32), **kw)


def test_a_local_default_setup_has_no_warnings():
    assert startup_warnings(s(), "127.0.0.1") == []


def test_public_mode_without_a_trusted_proxy_warns_that_every_visitor_shares_one_ip():
    [w] = startup_warnings(public(), "127.0.0.1")
    assert "TRUST_PROXY" in w and "one client" in w


def test_a_non_loopback_bind_without_a_trusted_proxy_warns():
    [w] = startup_warnings(s(), "0.0.0.0")
    assert "TRUST_PROXY" in w


def test_a_trusted_proxy_on_a_public_bind_warns_that_the_header_can_be_forged():
    [w] = startup_warnings(s(trust_proxy=True), "0.0.0.0")
    assert "X-Forwarded-For" in w and "forged" in w


def test_the_intended_deployment_is_quiet():
    assert startup_warnings(public(trust_proxy=True), "127.0.0.1") == []


def test_ipv6_loopback_and_localhost_count_as_loopback():
    assert startup_warnings(s(trust_proxy=True), "::1") == []
    assert startup_warnings(s(trust_proxy=True), "localhost") == []


def test_no_log_record_carries_a_secret_value(monkeypatch, caplog):
    secrets = {"sess": "FAKE-SESSION-" + "x" * 32, "admin": "FAKE-ADMIN-" + "y" * 32}
    settings = s(
        public_origin="https://g.example.com",
        session_secret=SecretStr(secrets["sess"]),
        admin_token=SecretStr(secrets["admin"]),
    )
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: None)
    with caplog.at_level(logging.DEBUG):
        entry.main(["--host", "0.0.0.0"])
    assert "TRUST_PROXY" in caplog.text
    for record in caplog.records:
        text = record.getMessage() + repr(record.args) + repr(record.__dict__)
        for value in secrets.values():
            assert value not in text
