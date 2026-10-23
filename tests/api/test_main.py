import re
import tomllib
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

import gumshoe.api.__main__ as entry
from gumshoe.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def served(monkeypatch, tmp_path):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    settings = Settings(
        _env_file=None, api_host="127.0.0.2", api_port=9001, stats_db_path=tmp_path / "d.db"
    )
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_host_and_port_come_from_the_settings(served):
    entry.main([])
    assert served == [
        (
            ("gumshoe.api.__main__:build_app",),
            {
                "factory": True,
                "host": "127.0.0.2",
                "port": 9001,
                "reload": False,
                "proxy_headers": False,
            },
        )
    ]


def test_uvicorn_does_not_rewrite_the_client_from_forwarded_headers(served):
    entry.main([])
    [(_, kw)] = served
    assert kw["proxy_headers"] is False


def test_the_command_line_overrides_them_and_can_reload(served):
    entry.main(["--host", "0.0.0.0", "--port", "9000", "--reload"])
    [(_, kw)] = served
    assert (kw["host"], kw["port"], kw["reload"]) == ("0.0.0.0", 9000, True)


def test_the_factory_builds_the_app_on_the_configured_database(served, tmp_path):
    app = entry.build_app()
    assert isinstance(app, FastAPI) and (tmp_path / "d.db").is_file()


def test_the_api_is_installed_as_a_command():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["gumshoe-api"] == "gumshoe.api.__main__:main"


def test_the_env_example_names_only_real_settings_and_keeps_the_default_roles():
    variable = re.compile(r"^(#\s*)?([A-Z][A-Z0-9_]*)=")
    found = [
        m
        for line in (ROOT / ".env.example").read_text().splitlines()
        if (m := variable.match(line))
    ]
    assert [m[2] for m in found if m[2].lower() not in Settings.model_fields] == []
    live = [m[2] for m in found if m[1] is None]
    # following the README (copy, then fill in the key) must run Jev with Nimble as the shadow
    assert "DECIDER_PRIMARY" not in live and "DECIDER_SHADOW" not in live


def test_main_logs_the_warnings(served, caplog):
    with caplog.at_level("WARNING"):
        entry.main(["--host", "0.0.0.0"])
    assert "TRUST_PROXY" in caplog.text
